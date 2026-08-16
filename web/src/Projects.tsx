import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  uploadProject,
  uploadZip,
  waitForJob,
  type DirEntry,
  type DirListing,
  type Job,
  type ProjectInfo,
  type UploadStats,
} from "./api";
import { useLang } from "./i18n";

// --------------------------------------------------------------------------- //
// 업로드 대상 고르기
//
// 서버(server/upload.py)의 허용목록·제외폴더와 같은 값을 둔다. 서버에서도
// 다시 거르지만, 여기서 미리 걸러야 node_modules 수만 개를 네트워크로
// 올렸다가 서버에서 버리는 일이 없다.
// --------------------------------------------------------------------------- //
const ALLOWED = new Set([
  "java", "xml", "py", "sql", "jsp", "js", "ts", "tsx", "jsx",
  "properties", "yml", "yaml", "json", "html", "htm", "css", "scss",
  "md", "txt", "gradle", "cfg", "ini", "conf", "sh", "bat",
  "c", "h", "cpp", "cs", "go", "rb", "php", "kt", "scala", "groovy",
]);

const SKIP_DIRS = new Set([
  ".git", ".svn", ".hg", "node_modules", "__pycache__", ".idea", ".vscode",
  ".gradle", ".mvn", "target", "build", "out", "bin", "dist", "venv", ".venv",
]);

export interface Picked {
  file: File;
  path: string;
}

function keep(path: string): boolean {
  const parts = path.split("/");
  if (parts.some((p) => p.startsWith(".") || SKIP_DIRS.has(p))) return false;
  const ext = parts[parts.length - 1].split(".").pop()?.toLowerCase() ?? "";
  return ALLOWED.has(ext);
}

function fromFileList(list: FileList): Picked[] {
  const out: Picked[] = [];
  for (const file of Array.from(list)) {
    // webkitRelativePath 는 폴더 선택일 때만 채워진다. 낱개 파일은 이름뿐.
    const path = file.webkitRelativePath || file.name;
    if (keep(path)) out.push({ file, path });
  }
  return out;
}

/** 드롭된 항목을 훑는다. 폴더면 하위까지 내려간다. */
async function fromDataTransfer(items: DataTransferItemList): Promise<Picked[]> {
  const roots: FileSystemEntry[] = [];
  for (const item of Array.from(items)) {
    const entry = item.webkitGetAsEntry?.();
    if (entry) roots.push(entry);
  }

  const out: Picked[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    const path = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) =>
        (entry as FileSystemFileEntry).file(res, rej)
      );
      if (keep(path)) out.push({ file, path });
      return;
    }
    if (SKIP_DIRS.has(entry.name) || entry.name.startsWith(".")) return;
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries 는 한 번에 최대 100개만 준다. 빈 배열이 올 때까지 반복해야
    // 큰 폴더에서 앞 100개만 올라가는 일이 없다.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res, rej) =>
        reader.readEntries(res, rej)
      );
      if (batch.length === 0) break;
      for (const child of batch) await walk(child, path);
    }
  };

  for (const root of roots) await walk(root, "");
  return out;
}

/** 모든 경로가 같은 최상위 폴더를 공유하면 그 한 겹을 벗긴다.
 *  나눠 보내면 서버는 전체 목록을 볼 수 없으므로 여기서 처리한다. */
export function stripCommonRoot(entries: Picked[]): Picked[] {
  if (entries.length === 0) return entries;
  const tops = new Set(entries.map((e) => e.path.split("/")[0]));
  if (tops.size !== 1) return entries;
  // 최상위에 파일만 있는 경우(벗기면 이름이 사라진다)는 그대로 둔다
  if (entries.some((e) => !e.path.includes("/"))) return entries;
  return entries.map((e) => ({ ...e, path: e.path.slice(e.path.indexOf("/") + 1) }));
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// --------------------------------------------------------------------------- //
// 사이드바 프로젝트 전환기
// --------------------------------------------------------------------------- //
export function ProjectBar({
  projects,
  activeId,
  busy,
  onSwitch,
  onOpenPicker,
  onReparse,
  onRemove,
}: {
  projects: ProjectInfo[];
  activeId: string;
  busy: string | null;
  onSwitch: (id: string) => void;
  onOpenPicker: () => void;
  onReparse: (id: string) => void;
  onRemove: (p: ProjectInfo) => void;
}) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    addEventListener("mousedown", onDown);
    return () => removeEventListener("mousedown", onDown);
  }, [open]);

  const active = projects.find((p) => p.id === activeId);

  return (
    <div className="proj" ref={box}>
      <button className="proj-current" onClick={() => setOpen((v) => !v)}>
        <span className="proj-label">{t("projects")}</span>
        <span className="proj-name">{active?.name ?? "—"}</span>
        <span className="proj-caret">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div className="proj-menu">
          {projects.map((p) => (
            <div key={p.id} className={`proj-item ${p.id === activeId ? "active" : ""}`}>
              <button
                className="proj-pick"
                onClick={() => {
                  setOpen(false);
                  onSwitch(p.id);
                }}
              >
                <span className="proj-item-name">{p.name}</span>
                <span className="proj-item-sub">
                  {p.missing_roots.length > 0
                    ? t("missingRoot")
                    : busy === p.id
                      ? t("parsing")
                      : p.parsed
                        ? t("programsCount", { n: p.counts.programs ?? "–" })
                        : t("notParsed")}
                </span>
                <span className="proj-item-path" title={p.roots.join(", ")}>
                  {p.builtin ? t("builtinTag") : p.roots[0]}
                </span>
              </button>
              <div className="proj-actions">
                <button onClick={() => onReparse(p.id)} title={t("reparse")}>
                  ↻
                </button>
                {!p.builtin && (
                  <button onClick={() => onRemove(p)} title={t("removeProject")}>
                    ✕
                  </button>
                )}
              </div>
            </div>
          ))}
          <button
            className="proj-open"
            onClick={() => {
              setOpen(false);
              onOpenPicker();
            }}
          >
            {t("openFolder")}
          </button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 로컬 폴더 탐색기
// --------------------------------------------------------------------------- //
const RECENT_KEY = "llmwiki.recentDirs";
const MAX_RECENT = 6;

function readRecent(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((v) => typeof v === "string") : [];
  } catch {
    return [];
  }
}

function pushRecent(path: string): string[] {
  const next = [path, ...readRecent().filter((p) => p !== path)].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* 저장 못 해도 이번 세션에서는 동작한다 */
  }
  return next;
}

/** 탐색기 좌측 트리 노드. children 은 펼칠 때 받아온다. */
interface TreeNode {
  path: string;
  name: string;
  children: DirEntry[] | null;
}

// --------------------------------------------------------------------------- //
// 내 컴퓨터에서 업로드
// --------------------------------------------------------------------------- //
function Uploader({
  onOpened,
  onBusy,
}: {
  onOpened: (projectId: string) => void;
  onBusy: (busy: boolean) => void;
}) {
  const { t } = useLang();
  const [picked, setPicked] = useState<Picked[]>([]);
  const [isZip, setIsZip] = useState(false);
  const [name, setName] = useState("");
  const [over, setOver] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [stats, setStats] = useState<UploadStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const abort = useRef<(() => void) | null>(null);

  const dirInput = useRef<HTMLInputElement>(null);
  const zipInput = useRef<HTMLInputElement>(null);

  // webkitdirectory 는 React 의 표준 props 에 없다. 속성으로 직접 단다.
  useEffect(() => {
    dirInput.current?.setAttribute("webkitdirectory", "");
    dirInput.current?.setAttribute("directory", "");
  }, []);

  const busy = sent !== null || !!job;
  useEffect(() => onBusy(busy), [busy, onBusy]);

  const total = useMemo(
    () => picked.reduce((sum, p) => sum + p.file.size, 0),
    [picked]
  );

  const take = (entries: Picked[], zip: boolean, fallbackName: string) => {
    setErr(null);
    setStats(null);
    setIsZip(zip);
    setPicked(entries);
    if (entries.length === 0) {
      setErr(t("uploadNothing"));
      return;
    }
    // 폴더를 올리면 경로 첫 마디가 폴더 이름이다.
    const top = entries[0].path.split("/")[0];
    setName(zip ? fallbackName.replace(/\.zip$/i, "") : entries.length && top ? top : fallbackName);
  };

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (busy) return;
    const dt = e.dataTransfer;
    const files = Array.from(dt.files);
    if (files.length === 1 && files[0].name.toLowerCase().endsWith(".zip")) {
      take([{ file: files[0], path: files[0].name }], true, files[0].name);
      return;
    }
    try {
      take(await fromDataTransfer(dt.items), false, "upload");
    } catch (ex) {
      setErr((ex as Error).message);
    }
  };

  const start = async () => {
    if (picked.length === 0) return;
    setErr(null);
    setSent(0);
    try {
      const { promise, abort: cancel } = isZip
        ? uploadZip(picked[0].file, name, (s) => setSent(s))
        : uploadProject(stripCommonRoot(picked), name, (s) => setSent(s));
      abort.current = cancel;
      const res = await promise;
      setSent(null);
      setStats(res.upload);
      const done = await waitForJob(res.job, setJob);
      setJob(null);
      if (done.state === "failed") {
        setErr(`${t("parseFailed")}: ${done.error}`);
        return;
      }
      onOpened(res.project.id);
    } catch (ex) {
      setSent(null);
      setJob(null);
      setErr((ex as Error).message);
    } finally {
      abort.current = null;
    }
  };

  const pct = sent !== null && total > 0 ? Math.min(100, (sent / total) * 100) : 0;

  return (
    <div className="up-panel">
      <p className="fp-hint">{t("uploadHint")}</p>

      <div
        className={`up-drop ${over ? "over" : ""} ${busy ? "busy" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <div className="up-drop-icon">📁</div>
        <div className="up-drop-text">{t("uploadDrop")}</div>
        <div className="up-drop-actions">
          <button className="btn" onClick={() => dirInput.current?.click()} disabled={busy}>
            {t("uploadPickFolder")}
          </button>
          <button
            className="sb-mini"
            onClick={() => zipInput.current?.click()}
            disabled={busy}
          >
            {t("uploadPickZip")}
          </button>
        </div>
        <input
          ref={dirInput}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) take(fromFileList(e.target.files), false, "upload");
            e.target.value = "";
          }}
        />
        <input
          ref={zipInput}
          type="file"
          accept=".zip"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) take([{ file: f, path: f.name }], true, f.name);
            e.target.value = "";
          }}
        />
      </div>

      {err && <div className="sb-error">{err}</div>}

      {picked.length > 0 && (
        <div className="up-summary">
          <div className="up-line">
            <span className="up-key">{t("uploadSelected")}</span>
            <span className="up-val">
              {isZip
                ? t("uploadZipFile", { name: picked[0].file.name })
                : t("uploadFileCount", { n: picked.length })}
              {" · "}
              {formatBytes(total)}
            </span>
          </div>
          <label className="up-line">
            <span className="up-key">{t("uploadName")}</span>
            <input
              className="up-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              spellCheck={false}
            />
          </label>
        </div>
      )}

      {sent !== null && (
        <div className="up-progress">
          <div className="up-bar">
            <div className="up-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="up-pct">
            {t("uploading")} {pct.toFixed(0)}% ({formatBytes(sent)} / {formatBytes(total)})
          </span>
        </div>
      )}

      {stats && stats.skipped > 0 && (
        <div className="up-note">
          {t("uploadSkipped", { n: stats.skipped })}
          {stats.reasons.length > 0 && ` — ${stats.reasons.join(", ")}`}
        </div>
      )}

      <footer className="up-foot">
        {job && <span className="up-job">{job.message || t("parsing")}</span>}
        {sent !== null && (
          <button className="sb-mini" onClick={() => abort.current?.()}>
            {t("uploadCancel")}
          </button>
        )}
        <button className="btn" onClick={start} disabled={picked.length === 0 || busy}>
          {busy ? t("uploading") : t("uploadStart")}
        </button>
      </footer>
    </div>
  );
}

export function FolderPicker({
  onClose,
  onOpened,
}: {
  onClose: () => void;
  onOpened: (projectId: string) => void;
}) {
  const { t } = useLang();
  const [mode, setMode] = useState<"upload" | "server">("upload");
  const [uploading, setUploading] = useState(false);
  const [listing, setListing] = useState<DirListing | null>(null);
  const [typed, setTyped] = useState("");
  const [filter, setFilter] = useState("");
  const [cursor, setCursor] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(false);
  const [recent, setRecent] = useState<string[]>(() => readRecent());
  const [nodes, setNodes] = useState<Record<string, TreeNode>>({});
  const [open, setOpen] = useState<Set<string>>(new Set());
  const listRef = useRef<HTMLDivElement>(null);

  // 늦게 도착한 이전 요청이 최신 목록을 덮어쓰지 않게 한다.
  // (경로를 빠르게 입력하면 초기 로딩 응답이 뒤늦게 와서 홈으로 되돌아간다)
  const reqId = useRef(0);

  const load = useCallback((path?: string) => {
    const mine = ++reqId.current;
    setErr(null);
    setLoading(true);
    setFilter("");
    setCursor(0);
    api
      .listDir(path)
      .then((r) => {
        if (mine !== reqId.current) return;
        setListing(r);
        setTyped(r.path);
        // 지나온 폴더는 트리에 채워 둔다 — 다시 요청하지 않게
        setNodes((prev) => ({
          ...prev,
          [r.path]: { path: r.path, name: r.name, children: r.entries },
        }));
        setOpen((prev) => {
          const next = new Set(prev);
          r.crumbs.forEach((c) => next.add(c.path));
          return next;
        });
      })
      .catch((e) => mine === reqId.current && setErr(e.message))
      .finally(() => {
        if (mine === reqId.current) setLoading(false);
      });
  }, []);

  useEffect(() => load(), [load]);

  const toggleNode = useCallback(
    (entry: { path: string; name: string }) => {
      setOpen((prev) => {
        const next = new Set(prev);
        if (next.has(entry.path)) next.delete(entry.path);
        else next.add(entry.path);
        return next;
      });
      if (nodes[entry.path]?.children) return;
      api
        .listDir(entry.path)
        .then((r) =>
          setNodes((prev) => ({
            ...prev,
            [entry.path]: { path: r.path, name: r.name, children: r.entries },
          }))
        )
        .catch(() => undefined);
    },
    [nodes]
  );

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const all = listing?.entries ?? [];
    return needle ? all.filter((e) => e.name.toLowerCase().includes(needle)) : all;
  }, [listing, filter]);

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-row="${cursor}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const analyze = async () => {
    if (!listing) return;
    setErr(null);
    try {
      const { project, job: jobId } = await api.addProject(listing.path);
      const done = await waitForJob(jobId, setJob);
      setJob(null);
      if (done.state === "failed") {
        setErr(`${t("parseFailed")}: ${done.error}`);
        return;
      }
      setRecent(pushRecent(listing.path));
      onOpened(project.id);
    } catch (e) {
      setJob(null);
      setErr((e as Error).message);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (job) return;
    if (e.key === "Escape") {
      onClose();
      return;
    }
    // 경로 입력창에서는 방향키를 가로채지 않는다 (커서 이동이 우선)
    const inInput = (e.target as HTMLElement).tagName === "INPUT";
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (inInput && (e.target as HTMLInputElement).type !== "search") return;
      e.preventDefault();
      setCursor((c) =>
        Math.max(0, Math.min(shown.length - 1, c + (e.key === "ArrowDown" ? 1 : -1)))
      );
    } else if (e.key === "Enter" && !inInput) {
      e.preventDefault();
      if (shown[cursor]) load(shown[cursor].path);
    } else if (e.key === "Backspace" && !inInput && listing?.parent) {
      e.preventDefault();
      load(listing.parent);
    }
  };

  const hint = (p: { java: number; xml: number; capped: number }) =>
    t(p.capped ? "countHintCapped" : "countHint", { java: p.java, xml: p.xml });

  // capped 면 '못 찾았다'가 아니라 '다 세지 못했다'이다. 큰 폴더에서 0건으로
  // 단정하면 멀쩡한 프로젝트를 비어 있다고 잘못 알린다.
  const empty =
    listing &&
    listing.self.java === 0 &&
    listing.self.xml === 0 &&
    listing.self.capped === 0;

  return (
    <div className="sb-backdrop" onClick={() => !job && !uploading && onClose()}>
      <div
        className="fp-panel"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKey}
        tabIndex={-1}
      >
        <header className="sb-head">
          <strong>{t("addProjectTitle")}</strong>
          <button className="sb-close" onClick={onClose} disabled={!!job || uploading}>
            ✕
          </button>
        </header>

        <div className="fp-tabs">
          <button
            className={`fp-tab ${mode === "upload" ? "active" : ""}`}
            onClick={() => setMode("upload")}
            disabled={uploading}
          >
            {t("tabUpload")}
          </button>
          <button
            className={`fp-tab ${mode === "server" ? "active" : ""}`}
            onClick={() => setMode("server")}
            disabled={uploading}
          >
            {t("tabServer")}
          </button>
        </div>

        {mode === "upload" ? (
          <Uploader onOpened={onOpened} onBusy={setUploading} />
        ) : (
          <>
        <p className="fp-hint">{t("pickFolderHint")}</p>

        <div className="fp-path">
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load(typed)}
            placeholder={t("pathPlaceholder")}
            spellCheck={false}
          />
          <button className="sb-mini" onClick={() => load(typed)}>
            {t("goPath")}
          </button>
        </div>

        {err && <div className="sb-error">{err}</div>}

        <div className="fp-body">
          <aside className="fp-side">
            <div className="fp-side-head">{t("shortcuts")}</div>
            {listing?.links.map((l) => (
              <button
                key={l.path}
                className={`fp-link ${listing.path === l.path ? "active" : ""}`}
                onClick={() => load(l.path)}
                title={l.path}
              >
                {l.label}
              </button>
            ))}

            {recent.length > 0 && (
              <>
                <div className="fp-side-head">{t("recent")}</div>
                {recent.map((p) => (
                  <button key={p} className="fp-link" onClick={() => load(p)} title={p}>
                    {p.split("/").pop() || p}
                  </button>
                ))}
              </>
            )}

            <div className="fp-side-head">{t("folderTree")}</div>
            <div className="fp-tree">
              {listing && (
                <TreeRows
                  entries={nodes[listing.roots[0]]?.children ?? []}
                  rootPath={listing.roots[0]}
                  depth={0}
                  nodes={nodes}
                  open={open}
                  current={listing.path}
                  onToggle={toggleNode}
                  onPick={load}
                />
              )}
            </div>
          </aside>

          <div className="fp-main">
            <div className="fp-crumbs">
              {listing?.crumbs.map((c, i) => (
                <span key={c.path}>
                  {i > 0 && <span className="fp-sep">/</span>}
                  <button
                    className={`fp-crumb ${i === (listing.crumbs.length - 1) ? "last" : ""}`}
                    onClick={() => load(c.path)}
                  >
                    {c.label}
                  </button>
                </span>
              ))}
              <input
                className="fp-filter"
                type="search"
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value);
                  setCursor(0);
                }}
                placeholder={t("filterHere")}
              />
            </div>

            <div className={`fp-list ${loading ? "loading" : ""}`} ref={listRef}>
              {loading && !listing && <div className="sb-muted pad">{t("loading")}</div>}
              {listing?.parent && (
                <button className="fp-row up" onClick={() => load(listing.parent!)}>
                  <span className="fp-icon">⬆</span>
                  <span className="fp-name">{t("upFolder")}</span>
                </button>
              )}
              {shown.map((e, i) => (
                <button
                  key={e.path}
                  data-row={i}
                  className={`fp-row ${i === cursor ? "cursor" : ""}`}
                  onClick={() => load(e.path)}
                  onMouseEnter={() => setCursor(i)}
                >
                  <span className="fp-icon">📁</span>
                  <span className="fp-name">{e.name}</span>
                  {e.markers.map((m) => (
                    <span key={m} className="fp-marker" title={t("projectLikely")}>
                      {m}
                    </span>
                  ))}
                  {(e.java > 0 || e.xml > 0) && <span className="fp-count">{hint(e)}</span>}
                </button>
              ))}
              {listing && shown.length === 0 && (
                <div className="sb-muted pad">
                  {filter.trim() ? t("noMatchHere") : t("emptyFolder")}
                </div>
              )}
            </div>
          </div>
        </div>

        <footer className={`fp-foot ${empty ? "warn" : ""}`}>
          <div className="fp-current">
            <code>{listing?.path ?? ""}</code>
            {listing && (
              <span className={`fp-summary ${empty ? "warn" : ""}`}>
                {empty ? t("noSourcesHere") : hint(listing.self)}
                {listing.self.markers.length > 0 && ` · ${listing.self.markers.join(", ")}`}
              </span>
            )}
          </div>
          <span className="fp-keys">{t("keyHint")}</span>
          <button className="btn" onClick={analyze} disabled={!listing || !!job}>
            {job ? job.message || t("parsing") : t("analyzeThis")}
          </button>
        </footer>
          </>
        )}
      </div>
    </div>
  );
}

function TreeRows({
  entries,
  rootPath,
  depth,
  nodes,
  open,
  current,
  onToggle,
  onPick,
}: {
  entries: DirEntry[];
  rootPath: string;
  depth: number;
  nodes: Record<string, TreeNode>;
  open: Set<string>;
  current: string;
  onToggle: (e: { path: string; name: string }) => void;
  onPick: (path: string) => void;
}) {
  return (
    <>
      {depth === 0 && (
        <button
          className={`fp-tree-row ${current === rootPath ? "active" : ""}`}
          style={{ paddingLeft: 8 }}
          onClick={() => onPick(rootPath)}
        >
          <span className="fp-caret" />
          {rootPath.split("/").pop() || rootPath}
        </button>
      )}
      {entries.map((e) => {
        const isOpen = open.has(e.path);
        const children = nodes[e.path]?.children;
        return (
          <div key={e.path}>
            <button
              className={`fp-tree-row ${current === e.path ? "active" : ""}`}
              style={{ paddingLeft: 8 + (depth + 1) * 11 }}
              onClick={() => onPick(e.path)}
            >
              <span
                className="fp-caret"
                onClick={(ev) => {
                  ev.stopPropagation();
                  if (e.has_dirs) onToggle(e);
                }}
              >
                {e.has_dirs ? (isOpen ? "▾" : "▸") : ""}
              </span>
              {e.name}
            </button>
            {isOpen && children && (
              <TreeRows
                entries={children}
                rootPath={e.path}
                depth={depth + 1}
                nodes={nodes}
                open={open}
                current={current}
                onToggle={onToggle}
                onPick={onPick}
              />
            )}
          </div>
        );
      })}
    </>
  );
}
