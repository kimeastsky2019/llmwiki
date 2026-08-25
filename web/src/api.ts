import type { Lang } from "./i18n";

export interface ProgramNode {
  id: string;
  name: string;
  urls: string[];
  tables: string[];
  sql_count: number;
  has_doc: boolean;
}

export interface TreeLayer {
  layer: string;
  tiers: { tier: string; programs: ProgramNode[] }[];
}

export interface DocMeta {
  id: string;
  name: string;
  layer: string;
  entry: string;
  urls?: string[];
  classes?: string[];
  mappers?: string[];
  sql_ids?: string[];
  tables?: string[];
  service_ids?: string[];
  files?: string[];
  language?: Lang;
  generated_at?: string;
  generator?: string;
}

export interface DocResponse {
  id: string;
  meta: DocMeta;
  markdown: string;
}

export interface SearchHit {
  id: string;
  name: string;
  layer: string;
  score: number;
  matched: string[];
  snippet: string;
  tables: string[];
}

export interface Survey {
  files: number;
  capped: boolean;
  by_ext: { ext: string; count: number }[];
  skipped_dirs: string[];
}

export interface Readiness {
  ok: boolean;
  reason: string;
  hint: string;
  detail: string;
}

/** 형식별 준비 상태. 이미지 OCR 만 빠진 상태는 정상적으로 있을 수 있어 따로 알린다. */
export interface FormatReadiness {
  pdf: { ok: boolean; reason: string; hint: string };
  sheet: { ok: boolean; reason: string; hint: string };
  image: { ok: boolean; reason: string; hint: string; version?: string; languages?: string[] };
  /** 업로드가 받아들이는 확장자. 화면이 목록을 따로 들지 않게 서버가 준다. */
  suffixes: string[];
}

export interface ProviderInfo {
  id: string;
  model: string;
  /** 사내 GPU 에서 도는 모델인지 — 소스가 외부로 나가지 않는다 */
  local: boolean;
  ready: Readiness;
}

export interface Meta {
  project: string;
  project_id: string;
  parsed: boolean;
  survey: Survey | null;
  provider: string;
  provider_ready: Readiness;
  language: Lang;
  source_roots: string[];
  counts: Record<string, number>;
}

export interface ProjectInfo {
  id: string;
  name: string;
  roots: string[];
  builtin: boolean;
  parsed: boolean;
  parsed_at: string | null;
  added_at: string;
  counts: Record<string, number>;
  missing_roots: string[];
}

export interface DirProbe {
  java: number;
  xml: number;
  capped: number;
  has_dirs: boolean;
  markers: string[];
}

export interface DirEntry extends DirProbe {
  name: string;
  path: string;
}

export interface Crumb {
  label: string;
  path: string;
}

export interface DirListing {
  roots: string[];
  links: Crumb[];
  path: string;
  name: string;
  parent: string | null;
  crumbs: Crumb[];
  entries: DirEntry[];
  self: DirProbe;
}

export interface UploadStats {
  files: number;
  bytes: number;
  skipped: number;
  reasons: string[];
}

export interface UploadResult {
  project: ProjectInfo;
  upload: UploadStats;
  job: string;
}

export interface Job {
  id: string;
  kind: string;
  state: "running" | "done" | "failed";
  message: string;
  result: unknown;
  error: string | null;
}

export interface ProgramFacts {
  id: string;
  name: string;
  layer: string;
  entry: string;
  urls: string[];
  tables: string[];
  classes: string[];
  files: string[];
  sql_count: number;
}

export interface TableDetail {
  name: string;
  crud: string[];
  programs: { id: string; name: string; layer: string }[];
  statements: { id: string; kind: string; path: string; sql: string }[];
}

export interface SourceFile {
  path: string;
  size: number;
  lang: string;
  parsed: boolean;
}

export interface SourceRoot {
  index: number;
  name: string;
  path: string;
  files: SourceFile[];
}

export interface SourceContent {
  path: string;
  root: number;
  lang: string;
  lines: number;
  content: string;
}


// --------------------------------------------------------------------------
// AI 위험등급 산정 (STEP 1~5)
//
// 증적 기반 통제 판정과는 다른 파이프라인이다. 저쪽은 "이 통제가 충족됐나",
// 여기는 "이 서비스가 몇 등급인가" 를 32항목 배점으로 답한다.
// --------------------------------------------------------------------------
export interface RiskChecklistItem {
  id: string;
  text: string;
  weight_note?: number;
}

export interface RiskAxis {
  key: string;
  label: string;
  options: string[];
}

export interface RiskItemSpec {
  no: number;
  lv1: string;
  lv2: string;
  lv3: string;
  points: number;
  owner: string;
}

export interface RiskGradeBand {
  key: string;
  label: string;
  min: number;
  max: number;
  rank: number;
  override_applied?: boolean;
  override_from?: string;
  override_source?: string;
}

export interface RiskMaster {
  version: string;
  standard: Record<string, string>;
  high_impact: {
    rule: string;
    source: string;
    groups: { A: RiskChecklistItem[]; B: RiskChecklistItem[] };
  };
  safety: {
    rule: string;
    source: string;
    stages: string[];
    items: RiskChecklistItem[];
  };
  profile_axes: RiskAxis[];
  evaluation_set: { mapping_defined: boolean; note: string };
  mitigation_weights: { code: string; key: string; weight: number; label: string }[];
  not_mitigated_weight: number;
  grades: RiskGradeBand[];
  high_impact_override: { enabled: boolean; floor: string; source: string };
  rounding: { mode: string; display_decimals: number };
  items: RiskItemSpec[];
  technical_thresholds: {
    scored: boolean;
    entries: { items: number[]; metric: string; criterion: string; source: string }[];
  };
  invariant_problems: string[];
}

/** 항목 하나의 입력. residual 은 완화 적용(mitigated)일 때만 의미가 있다. */
export interface RiskItemInput {
  no: number;
  identified: boolean;
  mitigated: boolean;
  residual: string;
  note?: string;
}

export interface RiskInput {
  service_uuid?: string;
  service_name?: string;
  high_impact_a: string[];
  high_impact_b: string[];
  safety: Record<string, boolean>;
  safety_stage?: string;
  profile: Record<string, string>;
  items: RiskItemInput[];
}

export interface RiskRow extends RiskItemSpec {
  identified: boolean;
  mitigated: boolean;
  residual: string;
  weight: number;
  recognized_score: number;
  residual_score: number;
  note: string;
}

export interface RiskResult {
  service_uuid: string;
  service_name: string;
  step1_high_impact: {
    high_impact: boolean;
    a_count: number;
    b_count: number;
    rule: string;
    reason: string;
    source: string;
  };
  step1_safety: {
    applicable: boolean;
    safety_target: boolean | null;
    checked: Record<string, boolean>;
    rule: string;
    reason: string;
    source: string;
    stage: string;
  };
  step2_evaluation_set: { mapping_defined: boolean; note: string; axes: RiskAxis[] };
  step3_recognized_score: number;
  step4_residual_score: number;
  rows: RiskRow[];
  by_lv1: Record<string, { recognized: number; residual: number; points: number; count: number }>;
  computed_grade: RiskGradeBand;
  final_grade: RiskGradeBand;
  versions: Record<string, string>;
  assessed_at: string;
  derivation: string;
}


/** sLM 조언 — 판정이 아니다. 응답에 verdict 자리가 없는 것이 설계다. */
export interface RiskAdvisor {
  id: string;
  model: string;
  /** 사내에서 도는가 — true 면 프롬프트가 서버 밖으로 나가지 않는다 */
  local: boolean;
  ready: Readiness;
}

export interface RiskAdvice {
  item_no: number;
  stage: "identify" | "mitigate";
  /** 관련성. 위험이 있다는 판정이 아니라 눈여겨볼 정도다. */
  relevance: "high" | "medium" | "low" | "unclear";
  summary: string;
  checkpoints: string[];
  evidence: string[];
  mitigations: string[];
  provider: string;
  model: string;
  local: boolean;
  /** 사내 모델을 못 써서 외부로 넘어갔는가 — 화면이 반드시 알려야 한다 */
  fell_back: boolean;
  tried: { provider: string; error: string }[];
  error: string;
  derivation: string;
  facts: {
    programs?: string[];
    program_ids?: string[];
    urls?: string[];
    tables?: string[];
    layers?: string[];
    crud?: Record<string, string[]>;
  };
}

export interface RiskDraft {
  input: RiskInput;
  result: RiskResult;
  saved_at: string;
  saved_by: string;
}

export interface RiskDraftRow {
  service_uuid: string;
  service_name: string;
  saved_at: string;
  saved_by: string;
  residual_score: number | null;
  grade: string;
  high_impact: boolean | null;
}

// --------------------------------------------------------------------------
// 규제 지식그래프 · 근거기반 자동평가 (/api/reg/…)
//
// 여기 있는 것은 프로젝트 단위가 아니다. 소스 분석은 프로젝트마다 갈리지만
// 규제 그래프는 조직 전체에 하나뿐이라, 프로젝트를 바꿔도 같은 것을 본다.
// --------------------------------------------------------------------------
export interface RegVersions {
  ontology: string;
  ruleset: string;
  standard: string;
  provisions: { uuid: string; number: string; effective_from: string }[];
}

export interface RegAssessment {
  uuid: string;
  service_uuid: string;
  service_name: string;
  control_code: string;
  control_title: string;
  /** 유보를 반영한 최종 판정 */
  verdict: string;
  /** 룰이 계산한 값 — 유보로 넘어간 이유를 보려면 이 둘을 같이 봐야 한다 */
  raw_verdict: string;
  label: string;
  reason: string;
  triggers: string[];
  evidence_ids: string[];
  need: number;
  have: number;
  versions: RegVersions;
  assessed_at: string;
  as_of: string;
  /** 잠정 | 확정 — 노드 생애 상태와는 다른 축이다 */
  decision_status: string;
  confirmed_by: string;
  confirmed_at: string;
}

export interface RegMetrics {
  total: number;
  decided: number;
  deferred: number;
  auto_rate: number;
  by_verdict: Record<string, number>;
  by_trigger: Record<string, number>;
}

export interface RegAssessResponse {
  graph_seq: number;
  metrics: RegMetrics;
  verdict_labels: Record<string, string>;
  assessments: RegAssessment[];
}

export interface RegGraph {
  version: string;
  seq: number;
  edges: number;
  pending_changes: number;
  counts: Record<string, number>;
  coverage: Record<string, number>;
  system_functions: { linked: number; unlinked: number };
}

export interface RegCoverage {
  uncovered_obligations: {
    obligation: string;
    title: string;
    level: string;
    provisions: string[];
  }[];
  partially_covered: {
    obligation: string;
    title: string;
    control: string;
    mapping_type: string;
    note: string;
  }[];
  controls_without_evidence: { control: string; title: string }[];
  controls_without_procedure: { control: string; title: string }[];
  manual_controls: { control: string; title: string; note: string }[];
  summary: Record<string, number>;
}

export interface RegIssue {
  level: string;
  code: string;
  message: string;
}

export interface RegValidation {
  ok: boolean;
  errors: number;
  warnings: number;
  issues: RegIssue[];
}

export interface RegGoldset {
  total: number;
  decided: number;
  correct: number;
  deferred: number;
  coverage: number;
  precision: number;
  kappa: number;
  confusion: Record<string, Record<string, number>>;
  misses: {
    service: string;
    control: string;
    expected: string;
    actual: string;
    reason: string;
  }[];
  result: string;
}

export interface RegChangeOp {
  op: string;
  node_type?: string;
  edge_type?: string;
  source?: string;
  target?: string;
  props?: Record<string, unknown>;
  spans?: { doc_id: string; start: number; end: number; quote: string }[];
}

export interface RegChange {
  changeset_id: string;
  proposer: { type: string; id: string };
  source: { type: string; id: string } | null;
  ops: RegChangeOp[];
  status: string;
  grade: string;
  impact: {
    affected_controls: number;
    affected_control_codes: string[];
    affected_assessments: number;
    affected_services: number;
    breaking: boolean;
  };
  checks: { shacl?: string; issues?: RegIssue[] };
  created_at: string;
  reviewed_by: string;
  reviewed_at: string;
  review_note: string;
}

export interface RegChangeDetail extends RegChange {
  approver: string;
  diff?: {
    added_nodes: { id: string; type: string; props: Record<string, unknown> }[];
    added_edges: { key: string; type: string; source: string; target: string }[];
    changed_nodes: { id: string; type: string; changes: Record<string, unknown[]> }[];
    obsoleted: string[];
  };
}

export interface RegGrade {
  approver: string;
  scope: string;
  breaking: string;
}

// --------------------------------------------------------------------------
// 문서 지식베이스 — 글·표·그림·엑셀 4채널
//
// 규제 그래프와 다른 층이다. 저쪽은 조직의 의무와 통제를 다루고, 여기는 문서
// 한 건이 적재돼도 되는지를 적재 직전에 가른다.
// --------------------------------------------------------------------------
export interface KbSector {
  code: string;
  name: string;
  name_ko: string;
  ksic: string;
  energy_sources: string[];
  key_equipment: string[];
  required_metrics: { code: string; label: string }[];
  unit_basis: string;
  partition: string;
  notes: string;
}

/** 문서 내용이 실제로 도달하는 곳. `cross_border` 가 국외 이전 해당성을 가른다
 *  (개인정보보호법 제28조의8). 화면이 이름만 보고 국내/국외를 추측하지 않도록
 *  판정에 쓰는 값을 서버가 그대로 내려준다. */
export interface KbDestination {
  provider: string;
  name: string;
  cross_border: boolean;
  note: string;
}

export interface KbHealth {
  status: string;
  ontology: string;
  channels: string[];
  sectors: number;
  /** pdfplumber 가 없으면 업로드하기 전에 알려 준다 */
  parser_ready: Readiness & { formats?: FormatReadiness };
  /** 서버 설정이 정한 기본 목적지 (config.yaml 의 kb.destination → llm.provider) */
  destination: KbDestination;
  /** 화면에서 고를 수 있는 공급자. 목록의 유일한 출처다 — 화면이 따로 들고 있으면
   *  공급자가 늘었을 때 한쪽만 갱신되어 판정과 표시가 어긋난다. */
  destinations: KbDestination[];
  store: KbStats & { root: string };
}

export interface KbStats {
  documents: number;
  records: number;
  sectors: Record<string, number>;
  channels: Record<string, number>;
  masked_all: boolean;
}

export interface KbFinding {
  rule: string;
  law: string;
  article: string;
  severity: "blocker" | "error" | "warning" | "info";
  title: string;
  detail: string;
  samples: string[];
  remedy: string;
  /** 사람만 채운다 — 룰이 채운 값이 여기 오면 서버 검증이 막는다 */
  resolution: string | null;
}

export interface KbGateReport {
  verdict: "BLOCKED" | "CONDITIONAL" | "ALLOWED";
  verdict_label: string;
  upload_allowed: boolean;
  counts: Record<string, number>;
  pii_detected: number;
  masking_enabled: boolean;
  destination: { name: string; cross_border: boolean };
  findings: KbFinding[];
  note: string;
}

export interface KbMetric {
  code: string;
  label: string;
  evidence: string | null;
}

export interface KbCoverage {
  sector: string;
  sector_name: string;
  unit_basis: string;
  required: number;
  present: KbMetric[];
  missing: KbMetric[];
  coverage: number;
}

export interface KbParseSummary {
  filename: string;
  doc_hash: string;
  pages: number;
  text_blocks: number;
  text_chars: number;
  tables: number;
  table_rows: number;
  numeric_cells: number;
  images: number;
  image_kinds: Record<string, number>;
  warnings: string[];
}

export interface KbGraphStats {
  nodes: number;
  edges: number;
  quantities: number;
  findings: number;
  by_type: Record<string, number>;
  by_derivation: Record<string, number>;
}

/** 채널별 실제 내용. 개수만으로는 무엇이 들어왔는지 확인할 수 없어 눈으로 대조하는 자리다.
 *  원문 적재가 막힌 문서는 `masked=true` 로 비식별된 것만 내려온다. */
export interface KbPreview {
  masked: boolean;
  text: { anchor: string; page: number; chars: number; content: string }[];
  table: {
    anchor: string;
    page: number;
    caption: string;
    header: string[];
    rows: string[][];
    numeric_cells: number;
  }[];
  /** `indexed=false` 는 로고 — 검색 대상에서 빠지지만 목록에는 남긴다.
   *  조용히 사라지면 그림 개수가 왜 다른지 알 수 없다. */
  image: {
    anchor: string;
    page: number;
    kind: string;
    width: number;
    height: number;
    caption: string;
    indexed: boolean;
  }[];
}

export interface KbAnalysis {
  filename: string;
  doc_hash: string;
  sector: string;
  sector_name: string;
  needs_review: boolean;
  partition: string;
  /** 원문 그대로 적재해도 되는가 — 진단서에는 담당자 연락처가 거의 항상 있어 보통 false */
  upload_allowed_raw: boolean;
  /** 비식별 처리를 거치면 적재해도 되는가 */
  upload_allowed: boolean;
  channels: Record<string, number>;
  parse_summary: KbParseSummary;
  classification: {
    sector: string;
    sector_name: string;
    ksic: string;
    confidence: number;
    needs_review: boolean;
    method: string;
    reason: string;
    unit_basis: string;
    votes: { sector: string; sector_name: string; score: number; matched: string[] }[];
  };
  coverage: KbCoverage;
  gate: KbGateReport;
  masking: { masked_count: number; residual_count: number; clean: boolean;
             residual: { label: string; value: string }[] };
  graph_stats: KbGraphStats;
  validation: { ok: boolean; errors: number; warnings: number };
  excel_path: string | null;
  has_graph: boolean;
  graph?: { nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] };
  /** 채널별 내용. 응답에만 있고 적재 저장소에는 복제하지 않는다. */
  preview?: KbPreview;
  /** 무엇을 기준으로 국외 이전 해당성을 판정했는지 */
  destination?: KbDestination;
  errors: string[];
  /** /ingest 응답에만 있다. stored 가 0 이면 skipped 에 이유가 담긴다. */
  stored?: {
    stored: number;
    partition: string | null;
    by_channel?: Record<string, number>;
    masked?: boolean;
    skipped?: string;
    path?: string;
  };
}

export interface KbDocument {
  doc_hash: string;
  filename: string;
  sector: string;
  sector_name: string;
  partition: string;
  stored: number;
  by_channel: Record<string, number>;
  masked: boolean;
  masked_count: number;
  pii_detected: number;
  verdict: string;
  graph_nodes: number;
  ingested_at: string;
}

export interface KbDocumentDetail extends KbDocument {
  analysis: KbAnalysis | null;
  graph_stats: KbGraphStats | null;
  has_excel: boolean;
}

export interface KbHit {
  doc_hash: string;
  filename: string;
  sector: string;
  sector_name: string;
  channel: string;
  anchor: string;
  page: number | null;
  score: number;
  snippet: string;
}


// --- 엔진 레이어 (/api/engines) --------------------------------------------- #
export type EngineStatus = "ok" | "idle" | "unavailable";

export interface EngineInfo {
  code: string;
  provider: string;
  status: EngineStatus;
  detail: {
    model?: string;
    base_url?: string;
    configured?: boolean;
    reason?: string;
    hint?: string;
    wiki_pages?: number;
    wiki_terms?: number;
    kb_documents?: number;
    kb_records?: number;
    rrf_k?: number;
    nodes?: number;
    ruleset?: string;
    standard?: string;
    journal_records?: number;
    destination?: string;
    cross_border?: boolean;
  };
}

export interface EnginesResponse {
  engines: EngineInfo[];
  default_provider: string;
  routing: {
    internal_only_acl: string[];
    examples: {
      task: string;
      acl: string;
      tier: string;
      provider: string;
      external_allowed: boolean;
      reason: string;
    }[];
  };
  checked_at: string;
  cached: boolean;
}

// --- 에너지 진단 위키 (/api/wiki) ------------------------------------------- #
export type WikiAcl = "public" | "internal" | "confidential" | "restricted";
export type WikiStatus = "draft" | "reviewed" | "deprecated";

export interface WikiSpan {
  doc: string;
  pages: number[];
  section?: string;
  anchor?: string;
}

export interface WikiPageSummary {
  stable_id: string;
  type: string;
  title: string;
  acl: WikiAcl;
  status: WikiStatus;
  version: number;
  numeric_verified: boolean;
  owner: string;
  domain: string;
  measurement_basis: string;
  confidence: string;
  tags: string[];
  related: string[];
  source_span: WikiSpan[];
  updated_at: string;
  path: string;
}

export interface WikiFinding {
  code: string;
  severity: "blocker" | "error" | "warning" | "info";
  page: string;
  message: string;
  hint: string;
  detail: Record<string, unknown>;
}

export interface WikiJournalRow {
  at: string;
  stable_id: string;
  type: string;
  version: number;
  decision: string;
  status: WikiStatus;
  actor: string;
  note: string;
  acknowledged_unverified: boolean;
  numeric_verified: boolean;
  findings: string[];
}

export interface WikiPageDetail {
  page: WikiPageSummary & {
    front_matter: Record<string, unknown>;
    body: string;
    raw: string;
  };
  backlinks: WikiPageSummary[];
  findings: WikiFinding[];
  review: WikiJournalRow[];
}

export interface WikiLint {
  pages: number;
  deployable: boolean;
  clean: boolean;
  counts: Record<string, number>;
  total: number;
  findings: WikiFinding[];
}

export interface WikiStats {
  pages: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_acl: Record<string, number>;
  numeric_verified: number;
  broken_pages: number;
}

export interface WikiFactor {
  code: string;
  label: string;
  value: number;
  unit: string;
  valid_from: string;
  valid_until: string;
  basis: string;
  source: string;
  dimension: string;
  mislabeled_as: string;
  expires_in_days: number | null;
}

export interface WikiReviewStats {
  records: number;
  by_decision: Record<string, number>;
  reviewers: Record<string, number>;
  acknowledged_unverified: number;
  last_at: string;
}

export interface WikiHealth {
  status: string;
  contract: string;
  pipeline_version: string;
  root: string;
  store: WikiStats;
  units: { version: string; standard: string; expiring: WikiFactor[] };
  lint: Omit<WikiLint, "findings">;
  parser_ready: { ok: boolean; reason: string; hint: string; formats?: FormatReadiness };
  destination: { name: string; cross_border: boolean; note: string };
  review: WikiReviewStats;
}

export interface WikiCheck {
  label: string;
  stated: number | null;
  computed: number;
  unit: string;
  formula: string;
  inputs: Record<string, unknown>;
  source: string;
  ok: boolean;
  delta_pct: number | null;
  note: string;
}

export interface WikiBuildResult {
  analysis: KbAnalysis;
  gate_allowed: boolean;
  summary: {
    pages: number;
    by_type: Record<string, number>;
    site_key: string;
    period: string;
    warnings: string[];
    verified_pages: number;
    extraction: Record<string, number | string | boolean | null>;
  };
  warnings: string[];
  checks: WikiCheck[];
  checks_failed: WikiCheck[];
  pages: WikiPageSummary[];
  stored: boolean;
  skipped?: string;
  lint?: Omit<WikiLint, "findings">;
}

export interface WikiHit {
  stable_id: string;
  title: string;
  type: string;
  acl: WikiAcl;
  status: WikiStatus;
  numeric_verified: boolean;
  score: number;
  ranks: Record<string, number>;
  snippet: string;
}

export interface WikiQueueItem {
  stable_id: string;
  type: string;
  title: string;
  status: WikiStatus;
  acl: WikiAcl;
  numeric_verified: boolean;
  priority: number;
  reasons: string[];
  blocking: string[];
  findings: WikiFinding[];
}

export interface WikiSuggestion {
  stable_id: string;
  task: string;
  /** 실제로 탄 경로 */
  provider: string;
  /** 화면이 고른 경로. provider 와 다르면 등급이 끼어든 것이다. */
  requested: string;
  overridden: boolean;
  external: boolean;
  text: string;
  decision: { tier: string; reason: string; external_allowed: boolean };
  invented_numbers: string[];
  numeric_clean: boolean;
  warnings: string[];
}

/** 재분석 결과. 제안일 뿐이고, 반영은 `applyBody` 가 따로 한다. */
export interface WikiReanalysis extends WikiSuggestion {
  current_body: string;
  context_chars: number;
  context_pages: number[];
  decision: {
    tier: string;
    reason: string;
    external_allowed: boolean;
    structure_kept?: boolean;
  };
}

export interface WikiLogRow {
  at: string;
  action: string;
  stable_id: string;
  type: string;
  version: number;
  status: string;
  acl: string;
  actor: string;
  note: string;
}

export interface WikiTypeInfo {
  name: string;
  ko: string;
  en: string;
  prefix: string;
}

/** 서버 오류 메시지도 뷰어 언어를 따르도록 모든 요청에 lang 을 붙인다.
 *  프로젝트도 마찬가지 — 서버에 상태를 두지 않으면 탭을 여러 개 열어도 안 꼬인다. */
let currentLang: Lang = "ko";
let currentProject: string | null = null;

export function setApiLang(lang: Lang): void {
  currentLang = lang;
}

export function setApiProject(id: string | null): void {
  currentProject = id;
}

/** 서브경로 배포(/wiki/ 등) 대응. vite 의 base 를 그대로 따라간다.
 *  로컬 dev 는 base 가 "/" 라 아무것도 붙지 않는다. */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

function tag(url: string): string {
  const sep = url.includes("?") ? "&" : "?";
  const project = currentProject ? `&project=${encodeURIComponent(currentProject)}` : "";
  return `${BASE}${url}${sep}lang=${currentLang}${project}`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(tag(url), init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const get = request;

function post<T>(url: string, payload?: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
}


/* ── 진단 준비 (체크리스트 · 시계열) ─────────────────────────────────── */

export interface ChecklistItem {
  id: string;
  name: string;
  source: string;
  checked: string;
  note: string;
}

export interface ChecklistGroup {
  equipment: string;
  fields: string[];
  items: ChecklistItem[];
}

export interface ChecklistDraft {
  sector: string;
  sector_name: string;
  unit_basis: string;
  energy_sources: string[];
  groups: ChecklistGroup[];
  item_count: number;
  from_wiki: boolean;
  wiki_measures: number;
}

export interface Checklist {
  id: string;
  title: string;
  sector: string;
  subsector: string;
  site: string;
  homepage: string;
  owner: string;
  note: string;
  groups: ChecklistGroup[];
  updated_at: string;
}

export interface ChecklistSummary {
  id: string;
  title: string;
  sector: string;
  subsector: string;
  site: string;
  owner: string;
  item_count: number;
  updated_at: string;
}

export interface TimeseriesRow {
  stable_id: string;
  title: string;
  type: string;
  sector: string;
  sector_name: string;
  domain: string;
  year: string;
  status: string;
  numeric_verified: boolean;
  tags: string[];
}

export interface TimeseriesYear {
  year: string;
  pages: number;
  verified: number;
  by_type: Record<string, number>;
}

export interface Timeseries {
  rows: TimeseriesRow[];
  years: string[];
  by_year: TimeseriesYear[];
  undated: number;
  ledger_by_year: { year: string; documents: number }[];
  sectors: KbSector[];
}

export const api = {
  meta: () => get<Meta>("/api/meta"),
  tree: () => get<TreeLayer[]>("/api/tree"),
  doc: (id: string) => get<DocResponse>(`/api/doc/${id}`),
  programFacts: (id: string) => get<ProgramFacts>(`/api/program/${id}`),
  search: (q: string) =>
    get<{ results: SearchHit[] }>(`/api/search?q=${encodeURIComponent(q)}`),
  tables: () =>
    get<{ name: string; crud: string[]; programs: string[] }[]>("/api/tables"),
  table: (name: string) => get<TableDetail>(`/api/table/${encodeURIComponent(name)}`),
  sourceTree: () => get<SourceRoot[]>("/api/source/tree"),
  source: (path: string, root?: number) =>
    get<SourceContent>(
      `/api/source?path=${encodeURIComponent(path)}` +
        (root === undefined ? "" : `&root=${root}`)
    ),
  excelUrl: (id: string) => tag(`/api/export/${id}.xlsx`),

  // --- 프로젝트 ---
  projects: () => get<{ projects: ProjectInfo[]; active: string }>("/api/projects"),
  addProject: (path: string, name?: string) =>
    post<{ project: ProjectInfo; job: string }>("/api/projects", { path, name }),
  reparse: (id: string) =>
    post<{ job: string }>(`/api/projects/${encodeURIComponent(id)}/parse`),
  activate: (id: string) =>
    post<{ active: string }>(`/api/projects/${encodeURIComponent(id)}/activate`),
  removeProject: (id: string) =>
    request<{ removed: boolean }>(`/api/projects/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  // --- 폴더 탐색 · 작업 ---
  listDir: (path?: string) =>
    get<DirListing>(`/api/fs/list${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  providers: () =>
    get<{ providers: ProviderInfo[]; default: string }>("/api/providers"),
  generate: (docId?: string, provider?: string) =>
    post<{ job: string }>("/api/generate", { doc_id: docId, provider }),
  job: (id: string) => get<Job>(`/api/jobs/${id}`),

  // --- 규제 지식그래프 ---
  // 쓰기는 결재(approve/reject)와 확정 서명(confirm) 둘뿐이다.
  // 노드를 직접 만들거나 지우는 길은 API 에 없다 — 있으면 커밋 결재가 우회된다.
  reg: {
    /** 유보 사유 설명은 온톨로지(ontology.py)가 원본이다 — 화면에 복사해 두지 않는다. */
    schema: () =>
      get<{
        deferral_triggers: Record<string, string>;
        verdict_ko: Record<string, string>;
      }>("/api/reg/schema"),
    graph: () => get<RegGraph>("/api/reg/graph"),
    validate: () => get<RegValidation>("/api/reg/validate"),
    assess: (service?: string) =>
      get<RegAssessResponse>(
        `/api/reg/assess${service ? `?service=${encodeURIComponent(service)}` : ""}`
      ),
    coverage: () => get<RegCoverage>("/api/reg/coverage"),
    goldset: () => get<RegGoldset>("/api/reg/goldset"),
    changes: () =>
      get<{ grades: Record<string, RegGrade>; changes: RegChange[] }>("/api/reg/changes"),
    change: (id: string) =>
      get<RegChangeDetail>(`/api/reg/changes/${encodeURIComponent(id)}`),
    approve: (id: string, by: string, note?: string) =>
      post<RegChange>(`/api/reg/changes/${encodeURIComponent(id)}/approve`, { by, note }),
    reject: (id: string, by: string, note?: string) =>
      post<RegChange>(`/api/reg/changes/${encodeURIComponent(id)}/reject`, { by, note }),
    confirm: (uuid: string, by: string, verdict?: string, note?: string) =>
      post<Record<string, unknown>>(
        `/api/reg/assess/${encodeURIComponent(uuid)}/confirm`,
        { by, verdict, note }
      ),
    commit: () => post<{ assessments: number; records: number }>("/api/reg/assess/commit"),

    /** 위험등급 산정 — 계산은 서버가 한다. 화면은 입력만 모은다. */
    risk: {
      master: () => get<RiskMaster>("/api/reg/risk/master"),
      assess: (input: RiskInput) => post<RiskResult>("/api/reg/risk/assess", input),
      drafts: () => get<{ drafts: RiskDraftRow[] }>("/api/reg/risk/drafts"),
      draft: (uuid: string) =>
        get<RiskDraft>(`/api/reg/risk/draft/${encodeURIComponent(uuid)}`),
      save: (uuid: string, input: RiskInput, by: string) =>
        post<RiskDraft>(`/api/reg/risk/draft/${encodeURIComponent(uuid)}`, { input, by }),
      remove: (uuid: string) =>
        request<{ removed: boolean }>(
          `/api/reg/risk/draft/${encodeURIComponent(uuid)}`,
          { method: "DELETE" }
        ),

      /** 조언자 목록 — 누가 답할 수 있고 어디서 도는지 */
      advisors: () =>
        get<{ advisors: RiskAdvisor[]; local_first: string[] }>("/api/reg/risk/advisors"),
      /** 한 항목에 대한 조언. allow_external 없이는 외부로 넘어가지 않는다. */
      advise: (body: {
        item_no: number;
        stage: "identify" | "mitigate";
        service?: string;
        profile?: Record<string, string>;
        program_ids?: string[];
        note?: string;
        allow_external?: boolean;
      }) => post<RiskAdvice>("/api/reg/risk/advise", body),
    },
  },

  // --- 문서 지식베이스 ---
  // analyze 는 적재하지 않는다. 적재는 ingest 뿐이고, 서버의 게이트가 막으면
  // 분석 결과만 돌아온다 — 화면에서 우회할 방법은 없다.
  kb: {
    health: () => get<KbHealth>("/api/kb/health"),
    sectors: () => get<{ sectors: KbSector[]; count: number }>("/api/kb/sectors"),
    /** PDF 를 분석만 한다. 사람이 업종을 확정하는 자리를 남기기 위한 경로다.
     *  `provider` 는 이 문서를 보낼 LLM — 국외 이전 해당성이 여기서 갈린다. */
    analyze: (file: File, sector?: string, provider?: string) =>
      upload<KbAnalysis>("/api/kb/analyze", file, {
        sector,
        build_excel: "true",
        destination_provider: provider,
      }),
    /** 분석 후 게이트를 통과하면 업종 구획에 적재한다. */
    ingest: (file: File, sector?: string, provider?: string, mask = true) =>
      upload<KbAnalysis>("/api/kb/ingest", file, {
        sector,
        mask: String(mask),
        destination_provider: provider,
      }),
    documents: (sector?: string) =>
      get<{ documents: KbDocument[]; stats: KbStats }>(
        `/api/kb/documents${sector ? `?sector=${encodeURIComponent(sector)}` : ""}`
      ),
    document: (docHash: string) =>
      get<KbDocumentDetail>(`/api/kb/documents/${encodeURIComponent(docHash)}`),
    search: (q: string, sector?: string, channel?: string) =>
      get<{ results: KbHit[] }>(
        `/api/kb/search?q=${encodeURIComponent(q)}` +
          (sector ? `&sector=${encodeURIComponent(sector)}` : "") +
          (channel ? `&channel=${encodeURIComponent(channel)}` : "")
      ),
    excelUrl: (docHash: string) =>
      tag(`/api/kb/documents/${encodeURIComponent(docHash)}/tables.xlsx`),
    ttlUrl: (docHash: string) =>
      tag(`/api/kb/documents/${encodeURIComponent(docHash)}/graph.ttl`),
  },

  // --- 엔진 레이어 ---
  // 두 솔루션이 같은 엔진을 쓴다. 화면마다 따로 상태를 물으면 서로 다른 값을
  // 보여 주게 되므로 창구를 하나로 둔다.
  engines: {
    list: (refresh = false) =>
      get<EnginesResponse>(`/api/engines${refresh ? "?refresh=true" : ""}`),
  },

  // --- 에너지 진단 위키 ---
  // preview 는 저장하지 않는다. 사업장 키가 바뀌면 모든 stable_id 가 바뀌므로,
  // 사람이 눈으로 확인하는 단계를 화면에서도 강제한다.
  wiki: {
    health: () => get<WikiHealth>("/api/wiki/health"),
    schema: () => get<Record<string, unknown>>("/api/wiki/schema"),
    units: () =>
      get<{ version: string; standard: string; factors: WikiFactor[] }>("/api/wiki/units"),
    /** PDF → 페이지 초안. 저장하지 않는다. */
    preview: (file: File, site: string, sector?: string, owner?: string) =>
      upload<WikiBuildResult>("/api/wiki/preview", file, { site, sector, owner }),
    /** PDF → 위키 저장. 적재 게이트를 통과하지 못하면 아무것도 쓰지 않는다. */
    ingest: (file: File, site: string, sector?: string, owner?: string) =>
      upload<WikiBuildResult>("/api/wiki/ingest", file, { site, sector, owner }),
    pages: (acl: WikiAcl, type?: string, status?: string) =>
      get<{ pages: WikiPageSummary[]; stats: WikiStats; types: WikiTypeInfo[] }>(
        `/api/wiki/pages?acl=${acl}` +
          (type ? `&type=${encodeURIComponent(type)}` : "") +
          (status ? `&status=${encodeURIComponent(status)}` : "")
      ),
    page: (id: string, acl: WikiAcl) =>
      get<WikiPageDetail>(`/api/wiki/pages/${encodeURIComponent(id)}?acl=${acl}`),
    search: (q: string, acl: WikiAcl, type?: string) =>
      get<{ results: WikiHit[]; index: Record<string, unknown> }>(
        `/api/wiki/search?q=${encodeURIComponent(q)}&acl=${acl}` +
          (type ? `&type=${encodeURIComponent(type)}` : "")
      ),
    graph: (acl: WikiAcl) =>
      get<{ nodes: unknown[]; edges: unknown[]; stats: Record<string, number> }>(
        `/api/wiki/graph?acl=${acl}`
      ),
    lint: () => get<WikiLint>("/api/wiki/lint"),
    queue: () =>
      get<{ queue: WikiQueueItem[]; stats: WikiReviewStats }>("/api/wiki/review/queue"),
    journal: () =>
      get<{ journal: WikiJournalRow[]; stats: WikiReviewStats }>("/api/wiki/review/journal"),
    /** 검토 결정. 서명(actor)이 없으면 서버가 400 을 준다 — 화면에서 우회할 수 없다. */
    review: (
      id: string,
      body: {
        decision: "approve" | "reject" | "deprecate";
        actor: string;
        note?: string;
        acknowledge_unverified?: boolean;
      }
    ) => post<WikiJournalRow>(`/api/wiki/review/${encodeURIComponent(id)}`, body),
    /** 서술 초안 제안. 페이지를 고치지 않고 제안만 돌려준다.
     *  confidential 이상은 서버가 외부 모델 경로를 막고, 등급이 허용해도
     *  allow_external 없이는 나가지 않는다. */
    assist: (body: {
      stable_id: string;
      task?: string;
      /** 사내/외부 선택. 비우면 서버가 사내로 처리한다. */
      provider?: string;
      context?: string;
    }) => post<WikiSuggestion>("/api/wiki/assist", body),
    /** 원문 발췌를 근거로 페이지를 다시 쓴다. 저장하지 않는다. */
    reanalyze: (body: { stable_id: string; provider?: string }) =>
      post<WikiReanalysis>("/api/wiki/reanalyze", body),
    /** 재분석 결과를 반영한다. 서명이 필요하고, 반영하면 상태가 draft 로 돌아간다. */
    applyBody: (
      id: string,
      body: {
        body: string;
        actor: string;
        note?: string;
        acknowledge_numbers?: boolean;
        acknowledge_structure?: boolean;
      }
    ) =>
      post<{ action: string; version: number; status: string; invented_numbers: string[] }>(
        `/api/wiki/pages/${encodeURIComponent(id)}/apply`,
        body
      ),
    log: () => get<{ log: WikiLogRow[] }>("/api/wiki/log"),
    catalogUrl: () => tag("/api/wiki/index.md"),
  },

  /** 진단 준비. 위키를 읽어 만들 뿐 위키를 바꾸지 않는다. */
  audit: {
    draft: (sector: string) =>
      get<ChecklistDraft>(`/api/audit/checklist/draft?sector=${encodeURIComponent(sector)}`),
    list: () => get<{ checklists: ChecklistSummary[] }>("/api/audit/checklists"),
    get: (id: string) => get<Checklist>(`/api/audit/checklists/${encodeURIComponent(id)}`),
    save: (payload: Partial<Checklist>) => post<Checklist>("/api/audit/checklists", payload),
    remove: (id: string) =>
      request<{ deleted: string }>(`/api/audit/checklists/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),
    timeseries: (sector: string, type: string) =>
      get<Timeseries>(
        `/api/audit/timeseries?sector=${encodeURIComponent(sector)}&type=${encodeURIComponent(type)}`
      ),
  },
};

/** multipart 업로드. 진행률이 필요 없는 단발 파일이라 fetch 로 충분하다. */
function upload<T>(
  url: string,
  file: File,
  fields: Record<string, string | undefined>
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v);
  return request<T>(url, { method: "POST", body: form });
}

/** 업로드는 fetch 대신 XHR 을 쓴다 — fetch 는 업로드 진행률을 주지 않는다.
 *  레거시 소스는 수천 개 파일이라 진행 표시 없이는 멈춘 것처럼 보인다. */
function xhrPost<T>(
  url: string,
  form: FormData,
  onProgress?: (sent: number) => void,
  register?: (abort: () => void) => void
): Promise<T> {
  const xhr = new XMLHttpRequest();
  register?.(() => xhr.abort());
  return new Promise<T>((resolve, reject) => {
    xhr.upload.onprogress = (ev) => ev.lengthComputable && onProgress?.(ev.loaded);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* 파싱 실패하면 아래에서 상태코드로 처리 */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else {
        const detail = (body as { detail?: string } | null)?.detail;
        const err = new Error(detail ?? `HTTP ${xhr.status}`);
        // 4xx 는 다시 보내도 같은 답이다 — 재시도 대상에서 뺀다.
        (err as Error & { permanent?: boolean }).permanent =
          xhr.status >= 400 && xhr.status < 500;
        reject(err);
      }
    };
    xhr.onerror = () => reject(new Error("연결이 끊겼습니다."));
    xhr.onabort = () => {
      const err = new Error("업로드를 취소했습니다.");
      (err as Error & { permanent?: boolean }).permanent = true;
      reject(err);
    };
    xhr.open("POST", tag(url));
    xhr.send(form);
  });
}

/** 한 묶음의 상한. 요청 하나가 짧게 끝나야 중간에 안 끊긴다. */
const BATCH_FILES = 40;
const BATCH_BYTES = 4 * 1024 * 1024;
const RETRIES = 3;

function makeBatches(entries: { file: File; path: string }[]) {
  const out: { file: File; path: string }[][] = [];
  let cur: { file: File; path: string }[] = [];
  let bytes = 0;
  for (const e of entries) {
    // 한 파일이 상한보다 커도 혼자서는 보낸다 (그래야 빠지지 않는다)
    if (cur.length > 0 && (cur.length >= BATCH_FILES || bytes + e.file.size > BATCH_BYTES)) {
      out.push(cur);
      cur = [];
      bytes = 0;
    }
    cur.push(e);
    bytes += e.file.size;
  }
  if (cur.length > 0) out.push(cur);
  return out;
}

/** 폴더 업로드 — 작게 나눠 보내고, 끊긴 묶음만 다시 보낸다.
 *
 *  한 요청에 다 담으면 브라우저가 파일 수백 개를 읽어 본문을 만드는 동안
 *  첫 바이트가 나가지 않아 nginx 가 408 로 끊는다(실제로 겪은 증상).
 */
export function uploadProject(
  entries: { file: File; path: string }[],
  name: string,
  onProgress?: (sent: number, total: number) => void
): { promise: Promise<UploadResult>; abort: () => void } {
  let cancelled = false;
  let abortCurrent: (() => void) | null = null;
  let uploadId: string | null = null;

  const total = entries.reduce((sum, e) => sum + e.file.size, 0);

  const run = async (): Promise<UploadResult> => {
    const started = await request<{ upload_id: string }>("/api/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    uploadId = started.upload_id;

    let done = 0;
    for (const batch of makeBatches(entries)) {
      if (cancelled) throw new Error("업로드를 취소했습니다.");
      const form = new FormData();
      for (const e of batch) {
        form.append("files", e.file);
        form.append("paths", e.path);
      }
      const size = batch.reduce((s, e) => s + e.file.size, 0);

      for (let attempt = 1; ; attempt++) {
        try {
          await xhrPost(
            `/api/uploads/${uploadId}/files`,
            form,
            (sent) => onProgress?.(done + Math.min(sent, size), total),
            (a) => (abortCurrent = a)
          );
          break;
        } catch (e) {
          const err = e as Error & { permanent?: boolean };
          if (err.permanent || attempt > RETRIES || cancelled) throw err;
          // 잠깐 쉬었다 같은 묶음을 다시 보낸다 (같은 파일을 덮어쓰므로 안전)
          await new Promise((r) => setTimeout(r, 500 * attempt));
        }
      }
      done += size;
      onProgress?.(done, total);
    }

    return request<UploadResult>(`/api/uploads/${uploadId}/finish`, { method: "POST" });
  };

  const promise = run().catch(async (e) => {
    // 실패·취소하면 서버에 받다 만 폴더를 남기지 않는다
    if (uploadId) {
      await request(`/api/uploads/${uploadId}`, { method: "DELETE" }).catch(
        () => undefined
      );
    }
    throw e;
  });

  return {
    promise,
    abort: () => {
      cancelled = true;
      abortCurrent?.();
    },
  };
}

/** ZIP 은 파일 하나라 나눌 것이 없다 — 기존 단발 엔드포인트를 그대로 쓴다. */
export function uploadZip(
  file: File,
  name: string,
  onProgress?: (sent: number, total: number) => void
): { promise: Promise<UploadResult>; abort: () => void } {
  const form = new FormData();
  form.append("files", file);
  if (name) form.append("name", name);
  let abortCurrent: (() => void) | null = null;
  const promise = xhrPost<UploadResult>(
    "/api/projects/upload",
    form,
    (sent) => onProgress?.(sent, file.size),
    (a) => (abortCurrent = a)
  );
  return { promise, abort: () => abortCurrent?.() };
}

/** 작업이 끝날 때까지 폴링. onTick 으로 진행 메시지를 흘려 준다. */
export async function waitForJob(
  jobId: string,
  onTick?: (job: Job) => void,
  intervalMs = 700
): Promise<Job> {
  for (;;) {
    const job = await api.job(jobId);
    onTick?.(job);
    if (job.state !== "running") return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
