export interface User {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "recruiter" | "hiring_manager";
  tenant: { id: string; name: string; slug: string };
  permissions: string[];
}

export interface Job {
  id: string;
  title: string;
  department: string | null;
  location: string | null;
  status: string;
  external_ref: string | null;
  created_at: string;
  description: { id: string; version: number; text: string; created_at: string } | null;
  active_rubric: { id: string; version: number; job_description_version_id: string } | null;
  description_changed_since_rubric: boolean;
  application_counts: Record<string, number>;
  application_total: number;
}

export interface Criterion {
  id?: string;
  name: string;
  category: string;
  description: string;
  weight: number;
  required: boolean;
  evidence_terms: string[];
}

export interface Rubric {
  id: string;
  job_id: string;
  version: number;
  status: "draft" | "approved" | "superseded";
  proposed_by: string;
  model_config: Record<string, unknown>;
  is_mock_proposal: boolean;
  scoring_logic_version: string;
  approved_at: string | null;
  created_at: string;
  criteria: Criterion[];
  weight_total: number;
  validation_errors: string[];
}

export interface CandidateRow {
  application_id: string;
  candidate_name: string;
  candidate_email: string | null;
  job_id: string;
  job_title: string;
  score: number | null;
  score_exact: string | null;
  required_status: string | null;
  supported_skills: string[];
  missing_or_unclear: string[];
  extraction_confidence: string | null;
  status: string;
  status_detail: string | null;
  flags: string[];
  is_mock: boolean | null;
  source_system: string;
  submitted_at: string;
  document_id: string | null;
  document_filename: string | null;
}

export interface Evidence {
  quote: string;
  page: number | null;
  section: string | null;
  segment_index: number | null;
  term: string | null;
}

export interface Assessment {
  criterion_id: string;
  criterion_name: string;
  category: string;
  weight: number;
  required: boolean;
  level: string;
  level_points: number;
  contribution: number;
  contribution_exact: string;
  required_status: string | null;
  evidence: Evidence[];
  supported_points: string[];
  missing: string[];
  ambiguities: string[];
  rationale: string;
}

export interface EvaluationSummary {
  id: string;
  score: number;
  score_exact: string;
  required_status: string;
  extraction_confidence: string;
  is_mock: boolean;
  is_current: boolean;
  rubric_version_id: string;
  rubric_version: number | null;
  scoring_logic_version: string;
  model_config: Record<string, unknown>;
  created_at: string;
  assessments?: Assessment[];
}

export interface ApplicationDetail {
  application_id: string;
  job: { id: string; title: string };
  candidate: { id: string; full_name: string | null; email: string | null } | null;
  source_system: string;
  external_application_id: string | null;
  submitted_at: string;
  status: string;
  status_detail: string | null;
  flags: string[];
  flag_details: Record<string, any>[];
  duplicate_of_id: string | null;
  document: {
    id: string;
    filename: string;
    content_type: string;
    size_bytes: number;
    parse_status: string;
    parse_error: string | null;
    page_count: number | null;
    extraction_confidence: string;
    extraction_notes: string[];
    extracted_char_count: number;
  } | null;
  current_evaluation: EvaluationSummary | null;
  evaluation_history: EvaluationSummary[];
  can_reprocess: boolean;
  can_delete: boolean;
}

export interface PreviewCandidate {
  application_id: string;
  candidate_name: string;
  score: number | null;
  score_exact: string | null;
  required_status: string | null;
  supported_skills: string[];
  is_mock: boolean | null;
  link: string;
  attachment: string | null;
}

export interface Preview {
  valid: boolean;
  errors: string[];
  warnings: string[];
  requires_external_confirmation: boolean;
  to: string[];
  cc: string[];
  external_recipients: string[];
  job: { id: string; title: string };
  score_range: { min: number | null; max: number | null };
  candidate_count: number;
  candidates: PreviewCandidate[];
  subject: string;
  rendered_text: string;
  attachments_allowed: boolean;
  delivery_mode: "secure_links" | "attachments";
}

export interface EmailSend {
  id: string;
  job_id: string;
  sender_email: string;
  to: string[];
  cc: string[];
  external_recipients: string[];
  subject: string;
  application_ids: string[];
  score_min: number | null;
  score_max: number | null;
  include_attachments: boolean;
  status: string;
  delivery_status: string;
  provider: string;
  provider_message_id: string | null;
  failure_detail: string | null;
  created_at: string;
  accepted_at: string | null;
  status_note: string | null;
}
