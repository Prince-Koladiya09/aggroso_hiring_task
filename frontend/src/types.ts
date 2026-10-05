export type RequestType = 'ACCESS' | 'CORRECTION' | 'DELETION' | 'UNSUPPORTED';

export type RequestStatus =
  | 'NEW'
  | 'AWAITING_INFO'
  | 'VERIFICATION_PENDING'
  | 'VERIFIED'
  | 'VERIFICATION_FAILED'
  | 'PLANNING'
  | 'PLAN_REVIEW'
  | 'PLANNING_FAILED'
  | 'PLAN_APPROVED'
  | 'EXPORT_REVIEW'
  | 'AWAITING_ACTION_APPROVAL'
  | 'EXECUTING'
  | 'PARTIALLY_FAILED'
  | 'COMPLETED_PENDING_RECORD'
  | 'CLOSED'
  | 'REJECTED'
  | 'CANCELLED';

export interface DeadlineState {
  days_remaining: number;
  is_overdue: boolean;
  is_at_risk: boolean;
  deadline_status: 'OVERDUE' | 'AT_RISK' | 'ON_TRACK' | 'COMPLETED';
  due_at_iso: string;
}

export interface RequestSummary {
  id: string;
  type: RequestType;
  status: RequestStatus;
  requester_name: string;
  requester_email: string;
  account_id?: string;
  relationship: string;
  received_at: string;
  due_at: string;
  extended: boolean;
  correlation_id: string;
  created_by: string;
  deadline: DeadlineState;
}

export interface RequestDetail extends RequestSummary {
  description: string;
  extension_reason?: string;
  subject_profile_id?: string;
  timeline: Array<{
    seq: number;
    event_type: string;
    actor_id: string;
    actor_role: string;
    timestamp: string;
    payload: any;
  }>;
  disclaimer: string;
}

export interface UserProfile {
  id: string;
  username: string;
  role: 'analyst' | 'approver' | 'auditor';
  full_name: string;
  sample_password?: string;
}

export interface InventoryItem {
  id: string;
  source: string;
  record_id: string;
  classification: string;
  relevance: 'RELEVANT' | 'UNRELATED' | 'UNCERTAIN';
  decision: 'INCLUDE' | 'REDACT' | 'EXCLUDE_RETENTION' | 'EXCLUDE_UNRELATED' | 'NEEDS_REVIEW';
  reason: string;
  rule_ids: string[];
  override_by?: string;
  override_reason?: string;
  raw_data: any;
}

export interface ProposedAction {
  id: string;
  kind: 'CORRECTION' | 'DELETION';
  source: string;
  record_id: string;
  field?: string;
  before_value?: string;
  after_value?: string;
  strategy: string;
  risk_text: string;
  rule_ids: string[];
  status: string;
}

export interface ActionExecutionItem {
  proposed_action_id: string;
  kind: string;
  source: string;
  record_id: string;
  field?: string;
  before_value?: string;
  after_value?: string;
  strategy: string;
  risk_text: string;
  rule_ids: string[];
  proposed_status: string;
  action_id?: string;
  action_status: string;
  attempts: number;
  idempotency_key?: string;
  pre_image?: any;
  result?: any;
  last_error?: string;
}

export interface ToolCallItem {
  id: string;
  tool: string;
  status: 'OK' | 'ERROR' | 'DENIED';
  args: any;
  denial_reason?: string;
  result_summary?: string;
  rows: number;
  duration_ms: number;
  caller: string;
  at: string;
}

export interface AuditEventItem {
  id: string;
  seq: number;
  event_type: string;
  actor_id: string;
  actor_role: string;
  entity: string;
  payload: any;
  prev_hash: string;
  hash: string;
  correlation_id: string;
  timestamp: string;
}

export interface PolicyRule {
  name: string;
  description: string;
  parameters?: Record<string, any>;
}

export interface PolicyData {
  policy_version: string;
  organization: string;
  title: string;
  disclaimer: string;
  sla: {
    acknowledge_days: number;
    fulfil_days: number;
    extension_days: number;
    max_extensions: number;
    at_risk_days: number;
  };
  rules: Record<string, PolicyRule>;
  editable_subject_fields: string[];
  deletion_strategies: Record<string, string>;
}
