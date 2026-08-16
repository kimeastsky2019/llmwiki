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
  },
};

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
