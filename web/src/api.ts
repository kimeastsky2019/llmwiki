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

export interface Meta {
  project: string;
  provider: string;
  language: Lang;
  source_roots: string[];
  counts: Record<string, number>;
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

/** 서버 오류 메시지도 뷰어 언어를 따르도록 모든 요청에 lang 을 붙인다. */
let currentLang: Lang = "ko";

export function setApiLang(lang: Lang): void {
  currentLang = lang;
}

function withLang(url: string): string {
  return url + (url.includes("?") ? "&" : "?") + `lang=${currentLang}`;
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(withLang(url));
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => get<Meta>("/api/meta"),
  tree: () => get<TreeLayer[]>("/api/tree"),
  doc: (id: string) => get<DocResponse>(`/api/doc/${id}`),
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
  excelUrl: (id: string) => withLang(`/api/export/${id}.xlsx`),
};
