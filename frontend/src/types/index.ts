export type ClaimStatus = "NEW" | "PROCESSING" | "READY" | "REQUIRES_CORRECTION" | "HUMAN_REVIEW";

export interface ClaimRow {
  id: string; seq: number; control_number: string; patient_id: string; provider: string; provider_id: string;
  payer: string; payer_id: string; service_date: string; total_amount: number; status: ClaimStatus;
  readiness_score: number | null; issue_count: number; assigned_agent: string | null; initial_status: ClaimStatus | null;
  initial_score: number | null; version: number; procedures: string[]; updated_at: string;
}
export interface Evidence { type: string; ref: string | null; detail: string }
export interface ValidationRow {
  rule_id: string; name: string; status: "pass" | "fail" | "warning" | "not_applicable"; severity: string; dimension: string;
  resolution: string | null; explanation: string; evidence: Evidence[]; next_action: string; agent: string; claim_version: number;
}
export interface Proposal {
  id: number; claim_id: string; claim_version: number; rule_id: string; op: string; field: string; line_no: number | null;
  original_value: unknown; proposed_value: unknown; problem: string; evidence: Evidence[]; agent: string;
  confidence_note: string; requires_role: string; status: string; projected_status: string; validation_note: string;
}
export interface Conflict { id: string; agents: string[]; topic: string; description: string; status: string; resolution: string }
export interface Assessment {
  status: ClaimStatus; engine_status: ClaimStatus; readiness_score: number; dimension_scores: Record<string, number>;
  blocking_issues: { rule_id: string; severity: string; explanation: string; resolution: string; next_action: string; agent: string }[];
  warnings: { code: string; explanation: string; source: string; severity: string }[]; passed_checks: number;
  conflicts: Conflict[]; escalations: { source: string; agent: string; code: string; reason: string }[]; notes: string[];
  proposals: number; projected_status_if_approved: string; estimated_manual_minutes: number;
  synthesis: { assessment_summary: string; key_risks: string[]; recommended_status: string; unsupported_items: string[];
    conflict_adjudication: { conflict_id: string; opinion: string; rationale: string }[] } | null;
  independent_review: { verdict: string; recommended_status: string; rationale: string; missing_evidence: string[];
    challenges: { target: string; issue: string; evidence_refs: string[] }[] } | null;
  disagreements: Record<string, unknown>[]; ai: { depth: string; claude: string; openai: string };
  iterations: number; shared_state_version: number; duration_ms: number; disclaimer: string; claim_version: number;
}
export interface AgentInfo {
  key: string; name: string; responsibility: string; tools: string[];
  live: { status: string; claim_id: string | null; updated: string | null } | undefined;
  runs: number; avg_ms: number; failures: number; ai_runs: number; reassessments: number; tool_calls: number;
}
export interface LiveEvent { type: string; seq: number; ts: string; [k: string]: any }
export interface AuditEvent {
  id: number; claim_id: string | null; simulation_id: string | null; event_type: string; actor: string; actor_type: string;
  summary: string; details: any; ts: string;
}
