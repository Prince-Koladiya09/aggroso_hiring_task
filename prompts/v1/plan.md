<policy>
{policy_rules_json}
</policy>

<interpretation>
{interpretation_json}
</interpretation>

<inventory>
{inventory_xml}
</inventory>

Task:
Propose an ordered fulfilment plan using ONLY these read tools: {tool_list}.
Propose concrete modifying actions (CORRECTION or DELETION) strictly for records that are:
1. Classified as RELEVANT and not under EXCLUDE_RETENTION or legal hold.
2. Directly derived from the request.
3. Permitted by policy (e.g. editable fields only, appropriate deletion strategy).

For each step and proposed action:
- Explain risks in plain language (e.g., "Deleting ticket removes support history", "Field under legal hold excluded from deletion").
- Cite exact policy rule IDs (e.g., POL-RET-1, POL-RET-2, POL-APR-2, POL-APR-3).
- List questions or cautions for the human reviewer.

Respond ONLY with a JSON object matching PlanSchema.
