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
};

/** 업로드는 fetch 대신 XHR 을 쓴다 — fetch 는 업로드 진행률을 주지 않는다.
 *  레거시 소스는 수천 개 파일이라 진행 표시 없이는 멈춘 것처럼 보인다. */
export function uploadProject(
  entries: { file: File; path: string }[],
  name: string,
  onProgress?: (sent: number, total: number) => void
): { promise: Promise<UploadResult>; abort: () => void } {
  const form = new FormData();
  // files 와 paths 는 같은 순서로 나가야 짝이 맞는다.
  for (const e of entries) {
    form.append("files", e.file);
    form.append("paths", e.path);
  }
  if (name) form.append("name", name);

  const xhr = new XMLHttpRequest();
  const promise = new Promise<UploadResult>((resolve, reject) => {
    xhr.upload.onprogress = (ev) =>
      ev.lengthComputable && onProgress?.(ev.loaded, ev.total);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* 파싱 실패하면 아래에서 상태코드로 처리 */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResult);
      else {
        const detail = (body as { detail?: string } | null)?.detail;
        reject(new Error(detail ?? `HTTP ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("업로드 중 연결이 끊겼습니다."));
    xhr.onabort = () => reject(new Error("업로드를 취소했습니다."));
  });

  xhr.open("POST", tag("/api/projects/upload"));
  xhr.send(form);
  return { promise, abort: () => xhr.abort() };
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
