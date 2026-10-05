from typing import Any, Dict, List
from pydantic import BaseModel


class ToolDefinition(BaseModel):
    name: str
    tool_type: str                 # read | write | internal_write
    exposed_to_llm: bool
    allowed_states: List[str]
    allowed_roles: List[str]       # human role that invoked the workflow
    allowed_callers: List[str]     # AGENT | EXECUTOR | SYSTEM
    description: str
    requires_verification: bool = False
    write_scope: str = ""          # CORRECTION | DELETION for write tools


TOOL_REGISTRY: Dict[str, ToolDefinition] = {
    "lookup_profile_for_verification": ToolDefinition(
        name="lookup_profile_for_verification", tool_type="read", exposed_to_llm=False,
        allowed_states=["NEW", "AWAITING_INFO", "VERIFICATION_PENDING"],
        allowed_roles=["analyst"], allowed_callers=["SYSTEM"],
        description="Lookup profile in database for identity verification comparison."),
    "search_profiles": ToolDefinition(
        name="search_profiles", tool_type="read", exposed_to_llm=True, allowed_states=["PLANNING"],
        allowed_roles=["analyst"], allowed_callers=["AGENT"], requires_verification=True,
        description="Search user profile records by the verified subject's identifiers."),
    "search_tickets": ToolDefinition(
        name="search_tickets", tool_type="read", exposed_to_llm=True, allowed_states=["PLANNING"],
        allowed_roles=["analyst"], allowed_callers=["AGENT"], requires_verification=True,
        description="Search support tickets by verified requester email / profile ID, plus mentions of the verified subject's name."),
    "search_activity_logs": ToolDefinition(
        name="search_activity_logs", tool_type="read", exposed_to_llm=True, allowed_states=["PLANNING"],
        allowed_roles=["analyst"], allowed_callers=["AGENT"], requires_verification=True,
        description="Search activity logs for the verified subject profile ID."),
    "get_record": ToolDefinition(
        name="get_record", tool_type="read", exposed_to_llm=True,
        allowed_states=["PLANNING", "PLAN_REVIEW", "EXECUTING", "PARTIALLY_FAILED"],
        allowed_roles=["analyst", "approver"], allowed_callers=["AGENT", "EXECUTOR"],
        description="Fetch a single record by source database name and record ID."),
    "check_policy": ToolDefinition(
        name="check_policy", tool_type="read", exposed_to_llm=True, allowed_states=["ANY"],
        allowed_roles=["analyst", "approver", "auditor"], allowed_callers=["AGENT", "SYSTEM", "EXECUTOR"],
        description="Return the text of a policy rule and its parameters."),
    "generate_export": ToolDefinition(
        name="generate_export", tool_type="internal_write", exposed_to_llm=False, allowed_states=["EXPORT_REVIEW"],
        allowed_roles=["analyst"], allowed_callers=["SYSTEM"], requires_verification=True,
        description="Generates the redacted export artifact (does not write to source data)."),
    "apply_correction": ToolDefinition(
        name="apply_correction", tool_type="write", exposed_to_llm=False,
        allowed_states=["EXECUTING", "PARTIALLY_FAILED"],
        allowed_roles=["analyst", "approver"], allowed_callers=["EXECUTOR"],
        requires_verification=True, write_scope="CORRECTION",
        description="Applies an approved correction to a source database."),
    "delete_record": ToolDefinition(
        name="delete_record", tool_type="write", exposed_to_llm=False,
        allowed_states=["EXECUTING", "PARTIALLY_FAILED"],
        allowed_roles=["analyst", "approver"], allowed_callers=["EXECUTOR"],
        requires_verification=True, write_scope="DELETION",
        description="Executes an approved deletion or anonymisation on a source database."),
}


def get_llm_exposed_tools() -> List[Dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "type": t.tool_type}
            for t in TOOL_REGISTRY.values() if t.exposed_to_llm]
