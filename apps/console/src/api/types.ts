/**
 * Contract types — hand-written once against `contracts/golden/S06.json` and
 * `00_SHARED_CONTEXT.md` §6, with a test asserting every schema property appears here
 * (§7.1's cheap insurance). Generated-from-schema is the preferred path at integration;
 * these are the G0 fallback, and drift fails loudly in `contract_shape.test.ts`.
 */

export type Decision = "APPROVE" | "CHALLENGE" | "BLOCK" | "SILENT_ESCALATION";
export type BreakerState = "CLOSED" | "OPEN" | "HALF_OPEN";

export interface Beneficiary {
  account_last4?: string;
  beneficiary_id?: string;
  country?: string;
  first_seen?: string;
  last_modified?: string;
  last_modified_phrase?: string;
  name?: string;
  org_payment_count?: number;
  status?: string;
}

export interface Contribution {
  dimension: string;
  evidence_ref: string;
  label: string;
  points: number;
  raw: number;
  reason: string;
  weight: number;
  abstained?: boolean;
  scored_as_clean?: boolean;
}

export interface FieldDelta {
  field: string;
  expected: string;
  presented: string;
  severity: "critical" | "warning" | "cosmetic" | string;
}

export interface IntentConfidence {
  clamp_reason?: string;
  clamped_to?: number;
  excludes?: string[];
  excludes_reason?: string;
  formula?: string;
  penalties?: Array<{ factor: string; points: number; value: number; value_used: number; weight: number; abstained: boolean }>;
  penalty_total?: number;
  value: number;
}

export interface EvidenceNode {
  id: string;
  kind: string;
  label: string;
  detail?: string;
  state?: string;
  points?: number;
}

export interface EvidenceEdge {
  from: string;
  to: string;
  label?: string;
}

export interface EvidenceGraph {
  nodes: EvidenceNode[];
  edges: EvidenceEdge[];
}

export interface HardOverride {
  code: string;
  counterfactual?: string;
  reason: string;
  replaces_band: boolean;
}

export interface Counterfactual {
  kind: "categorical" | "numeric" | "withheld" | string;
  narrative: string | null;
  derivable_from?: string[] | null;
}

export interface Assessment {
  abstentions?: Array<Record<string, unknown>>;
  arithmetic?: { risk_score: number; coverage: number; contributions_subtotal: number; uncertainty_penalty: number; [k: string]: unknown };
  assessment_id: string;
  band_outcome: Decision;
  circuit_breaker?: { flags: string[]; state: BreakerState };
  contributions: Contribution[];
  control_label?: string | null;
  counterfactual?: Counterfactual | null;
  decided_at_step?: string | null;
  decision: Decision;
  duress_escalation: boolean;
  engine_version?: string;
  evidence_graph?: EvidenceGraph | null;
  floors_failed?: string[];
  forced_by?: { code: string; reason?: string } | string | null;
  hard_override?: HardOverride | null;
  intent_confidence: IntentConfidence;
  intent_id: string;
  latency_ms?: number;
  mode?: string;
  outcome: Decision;
  override_applied?: string | null;
  policy_version: string;
  preconditions_failed?: string[];
  required_actions?: string[];
  risk_score: number;
  scored_at?: string;
  top_reasons?: string[];
  visible_to_requester?: string;
}

export interface CapturedIntent {
  action: string;
  amount_display?: string;
  amount_minor_units?: number | null;
  beneficiary?: Beneficiary;
  channel: string;
  currency?: string;
  deadline_iso?: string | null;
  executive_id: string;
  extraction?: { confidence: number; fields_missing: string[]; injection_flags: string[]; mode: string };
  fingerprint_covered_fields?: Record<string, string | number | null>;
  fingerprint_field_order?: string[];
  fingerprint_hex?: string;
  intent_id: string;
  language?: string;
  operator_id?: string;
  purpose?: string | null;
  received_at?: string;
  scenario_id?: string;
  stated_urgency?: string;
  transcript_redacted?: string;
}

export interface Signals {
  behavioural?: { channel_switch_flags: string[]; deviation_score: number };
  beneficiary?: { account_last4?: string; beneficiary_id?: string; risk_score: number; status?: string };
  bundle_id?: string;
  channel?: { device_channel_score?: number; independent_channel?: boolean; secondary_approver_nominated_by_requester?: boolean };
  circuit_breaker?: { flags: string[]; state: BreakerState };
  communication?: {
    authenticity_score: number;
    detector_abstentions?: Array<{ detector: string; input_present: boolean; reason: string }>;
    stylometry_match?: number | null;
    video_abstain?: boolean;
    video_authenticity?: number | null;
    voice_abstain?: boolean;
    voice_authenticity?: number | null;
  };
  coverage?: number;
  dimensions_unavailable?: string[];
  fingerprint?: { field_deltas: FieldDelta[]; verdict: "MATCH" | "MISMATCH" | "NOT_YET_VERIFIED" | "UNVERIFIABLE" };
  identity?: { channel_registered?: boolean; confidence: number };
  intent_id: string;
  language?: { injection_flags: string[]; se_families_total?: number; se_indicator_families?: string[]; secrecy_flags?: string[]; stated_urgency?: string };
  produced_at?: string;
  replay?: { max_similarity: number; matched_utterance_id: string; method: string } | null;
}

export interface TimelineStep {
  detail: string;
  label: string;
  latency_ms: number;
  stage: string;
  started_at: string;
}

export interface ScenarioInfo {
  channel: string;
  "class": "ATTACK" | "LEGIT";
  description: string;
  expected_decision: string;
  expected_frictionless?: boolean;
  hero: number | null;
  id: string;
  proves?: string;
  title: string;
}

export interface Challenge {
  _answer_is_never_published: true;
  answer_hmac: string;
  attempts_allowed: number;
  attempts_used: number;
  challenge_id: string;
  cooldown_seconds: number;
  expires_at: string;
  kind: string;
  nonce: string;
  prompt: string;
}

export interface OobSession {
  channel_must_differ_from: string;
  code_bits?: number;
  confirmed_by?: string;
  derived_from?: string;
  expires_at: string;
  nonce: string;
  oob_id: string;
  read_by?: string;
  registered_contacts: string[];
  verification_code: string;
}

export interface CapabilityToken {
  amount_minor_units: number;
  expires_at: string;
  fingerprint_hex: string;
  issued_at: string;
  mac: string;
  policy_version: string;
  single_use: boolean;
  token_id: string;
}

/** One full scenario envelope — the fixture shape and the live-service shape. */
export interface ScenarioEnvelope {
  _mocked?: string;
  assessment: Assessment;
  capability_token: CapabilityToken | null;
  challenge: Challenge | null;
  coverage_note: string | null;
  intent: CapturedIntent;
  out_of_band: OobSession | null;
  scenario: ScenarioInfo;
  signals: Signals;
  timeline: TimelineStep[];
}

// --------------------------------------------------------------------------- audit wire

export interface AuditRecord {
  seq: number;
  record_id: string;
  timestamp: string;
  event_type: string;
  transaction_id: string | null;
  actor: string;
  payload: Record<string, unknown>;
  policy_version: string;
  policy_hash: string;
  prev_hash: string;
  record_hash: string;
  tampered_at?: string | null;
  tampered_field?: string | null;
}

export interface VerifyResult {
  ok: boolean;
  record_count: number;
  first_broken_seq: number | null;
  broken_field: string | null;
  broken_field_source: "chain_structure" | "hash_mismatch" | "demo_affordance" | null;
  detail: string | null;
  untrusted_from: number | null;
  head_hash: string | null;
  elapsed_ms: number;
}

export interface AskResult {
  answer: string;
  record_seqs: number[];
  facts: Record<string, unknown>;
  refused: boolean;
  refusal_kind: string | null;
  intent: string;
  computed_by: "python";
  narrated_by: "template" | "model";
  suggestions: string[];
}

export interface BenchReport {
  ran_at: string;
  mode: string;
  policy_version: string;
  block_threshold: number;
  metrics: {
    attack_block_rate: Fraction;
    legitimate_approval_success: Fraction;
    false_challenge_rate: Fraction;
    verification_time_ms: { p50: number; p95: number; sample: number; mode: string };
    explanation_completeness: Fraction;
    abstention_correctness: Fraction;
    prevented_fraudulent_value_minor_units: number;
    prevented_fraudulent_value_display: string;
  };
  confusion: { matrix: Record<string, Record<string, number>>; off_diagonal: Array<Record<string, unknown>> };
  sweep: Array<{ threshold: number; detection_rate: number | null; false_positive_rate: number | null }>;
  rows: BenchRow[];
  honesty: string;
}

export interface Fraction {
  numerator: number;
  denominator: number;
  value: number | null;
  display: string;
  pct: string;
  note?: string;
}

export interface CanaryRun {
  canary_id: string;
  variant: string;
  expected: string;
  actual: string;
  passed: boolean;
  risk_score: number | null;
  ran_at: string;
  note: string;
}

export interface CanaryHistory {
  runs: CanaryRun[];
  streak: number;
  total: number;
  all_passed: boolean;
  last_failure: CanaryRun | null;
  banner: { level: string; message: string; canary_id: string } | null;
}

export interface HealthResult {
  ok: boolean;
  chain_ok: boolean;
  record_count: number;
  mode: string;
  version: string;
}

export interface BenchRow {
  id: string;
  hero?: string | null;
  "class": "ATTACK" | "LEGIT";
  expected: string;
  actual: string;
  visible_to_requester?: string;
  risk_score?: number | null;
  latency_ms?: number;
  error?: string | null;
  override_applied?: string | null;
  amount_minor_units?: number | null;
}
