from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator

class RequestedChange(BaseModel):
    field: str
    new_value: str
    source_hint: Optional[str] = "profiles"

class MissingVerificationItem(BaseModel):
    item: str
    reason: str
    policy_rule: str

class SubjectIdentifiers(BaseModel):
    name: str
    email: str
    account_id: Optional[str] = None

REQUEST_TYPES = {"ACCESS", "CORRECTION", "DELETION", "UNSUPPORTED"}


class InterpretationSchema(BaseModel):
    request_type: str = Field(description="ACCESS | CORRECTION | DELETION | UNSUPPORTED")

    @field_validator("request_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        v = (v or "").upper()
        if v not in REQUEST_TYPES:
            raise ValueError(f"request_type must be one of {sorted(REQUEST_TYPES)}")
        return v

    type_matches_form: bool
    subject: SubjectIdentifiers
    scope_summary: str
    requested_changes: List[RequestedChange] = Field(default_factory=list)
    ambiguities: List[str] = Field(default_factory=list)
    missing_verification: List[MissingVerificationItem] = Field(default_factory=list)

class PlanStep(BaseModel):
    order: int
    tool: str
    purpose: str
    risk: str
    policy_rules: List[str] = Field(default_factory=list)

class SourceConsideration(BaseModel):
    source: str
    decision: str  # SEARCH | SKIP
    reason: str

class ProposedActionItem(BaseModel):
    kind: str  # CORRECTION | DELETION

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        v = (v or "").upper()
        if v not in ("CORRECTION", "DELETION"):
            raise ValueError("kind must be CORRECTION or DELETION")
        return v

    source: str
    record_id: str
    field: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    strategy: Optional[str] = "HARD_DELETE"
    risk: str
    policy_rules: List[str] = Field(default_factory=list)

class PlanSchema(BaseModel):
    steps: List[PlanStep] = Field(default_factory=list)
    sources_considered: List[SourceConsideration] = Field(default_factory=list)
    proposed_actions: List[ProposedActionItem] = Field(default_factory=list)
    overall_risks: List[str] = Field(default_factory=list)
    questions_for_reviewer: List[str] = Field(default_factory=list)


class SourcesSchema(BaseModel):
    sources_considered: List[SourceConsideration] = Field(default_factory=list)


class ClassifiedRecord(BaseModel):
    record_id: str
    relevance: str
    note: Optional[str] = ""


class ClassifySchema(BaseModel):
    classified: List[ClassifiedRecord] = Field(default_factory=list)


class NarrativeSchema(BaseModel):
    narrative: str
