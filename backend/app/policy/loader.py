from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml
from pydantic import BaseModel, Field

class PolicyRule(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)

class SlaPolicy(BaseModel):
    acknowledge_days: int = 3
    fulfil_days: int = 30
    extension_days: int = 30
    max_extensions: int = 1
    at_risk_days: int = 7

class VerificationLevelConfig(BaseModel):
    level: int
    fields: List[str]

class VerificationPolicy(BaseModel):
    access: VerificationLevelConfig
    correction: VerificationLevelConfig
    deletion: VerificationLevelConfig

class RetentionRuleConfig(BaseModel):
    blocks: List[str]
    rule_id: str
    years: Optional[int] = None

class RetentionPolicy(BaseModel):
    legal_hold: RetentionRuleConfig
    billing: RetentionRuleConfig
    security_audit: RetentionRuleConfig

class RedactionPattern(BaseModel):
    name: str
    regex: str

class RedactionPolicy(BaseModel):
    restricted_security_fields: List[str]
    restricted_internal_fields: List[str]
    patterns: List[RedactionPattern] = Field(default_factory=list)

class ApprovalsPolicy(BaseModel):
    ttl_hours: int = 72
    plan: Dict[str, Any] = Field(default_factory=dict)
    correction: Dict[str, Any] = Field(default_factory=dict)
    deletion: Dict[str, Any] = Field(default_factory=dict)
    export_release: Dict[str, Any] = Field(default_factory=dict)

class LlmPolicy(BaseModel):
    max_description_chars: int = 2000
    excerpt_chars: int = 160

class PolicyModel(BaseModel):
    policy_version: str
    organization: str
    title: str
    effective_date: str
    disclaimer: str
    sla: SlaPolicy
    rules: Dict[str, PolicyRule]
    verification: VerificationPolicy
    retention: RetentionPolicy
    redaction: RedactionPolicy
    editable_subject_fields: List[str]
    deletion_strategies: Dict[str, str]
    approvals: ApprovalsPolicy = Field(default_factory=ApprovalsPolicy)
    llm: LlmPolicy = Field(default_factory=LlmPolicy)

_policy_cache: Optional[PolicyModel] = None

def load_policy(path_str: Optional[str] = None) -> PolicyModel:
    global _policy_cache
    if _policy_cache is not None and path_str is None:
        return _policy_cache

    from app.core.config import settings
    file_path = Path(path_str or settings.POLICY_PATH)
    if not file_path.exists():
        raise FileNotFoundError(f"Policy file not found at {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    policy = PolicyModel(**data)
    if path_str is None:
        _policy_cache = policy
    return policy

def get_policy() -> PolicyModel:
    return load_policy()
