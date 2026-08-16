import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  setApiLang,
  setApiProject,
  waitForJob,
  type DocResponse,
  type Job,
  type Meta,
  type ProgramFacts,
  type ProviderInfo,
  type Readiness,
  type ProjectInfo,
  type SearchHit,
  type TableDetail,
  type TreeLayer,
} from "./api";
import { FolderPicker, ProjectBar } from "./Projects";
import {
  LANGS,
  LangContext,
  readStoredLang,
  storeLang,
  translate,
  useLang,
  type Lang,
  type StringKey,
} from "./i18n";
import Markdown from "./Markdown";
import SourceBrowser, { type SourceTarget } from "./SourceBrowser";

type Route =
  | { kind: "home" }
  | { kind: "program"; id: string }
  | { kind: "table"; name: string }
  | { kind: "tables" };

function parseRoute(path: string): Route {
  if (path.startsWith("/p/")) return { kind: "program", id: path.slice(3) };
  if (path.startsWith("/t/")) return { kind: "table", name: decodeURIComponent(path.slice(3)) };
  if (path === "/tables") return { kind: "tables" };
  return { kind: "home" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.pathname));
  const [meta, setMeta] = useState<Meta | null>(null);
  const [tree, setTree] = useState<TreeLayer[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceTarget | null>(null);
  const [browserOpen, setBrowserOpen] = useState(false);

  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [parsing, setParsing] = useState<string | null>(null);
  // 프로젝트/문서가 바뀌면 올려서 트리·문서를 다시 읽게 하는 카운터
  const [refresh, setRefresh] = useState(0);

  // 저장된 선택이 없으면 config.yaml 의 output.language 를 따른다 (/api/meta 응답).
  const [lang, setLangState] = useState<Lang>(() => readStoredLang() ?? "ko");
  const [langPinned, setLangPinned] = useState(() => readStoredLang() !== null);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    setLangPinned(true);
    storeLang(next);
  }, []);

  // 렌더 중에 맞춰 둔다. 자식의 effect 가 부모보다 먼저 도는 탓에,
  // effect 안에서 바꾸면 첫 요청이 이전 언어/프로젝트로 나갈 수 있다.
  setApiLang(lang);
  setApiProject(activeProject);

  const langValue = useMemo(
    () => ({
      lang,
      setLang,
      t: (key: StringKey, vars?: Record<string, string | number>) =>
        translate(lang, key, vars),
    }),
    [lang, setLang]
  );
  const t = langValue.t;

  const navigate = useCallback((path: string) => {
    history.pushState(null, "", path);
    setRoute(parseRoute(path));
  }, []);

  const openSource = useCallback((target: SourceTarget) => {
    setSource(target);
    setBrowserOpen(true);
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(location.pathname));
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const loadProjects = useCallback(
    () =>
      api
        .projects()
        .then((r) => {
          setProjects(r.projects);
          setActiveProject((cur) => cur ?? r.active);
          return r;
        })
        .catch((e) => {
          setError(e.message);
          return null;
        }),
    []
  );

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // 언어·프로젝트가 바뀌면 서버 메시지도 그 조건으로 다시 받는다.
  useEffect(() => {
    if (activeProject === null) return;
    api.meta().then(setMeta).catch((e) => setError(e.message));
    api.tree().then(setTree).catch((e) => setError(e.message));
  }, [lang, activeProject, refresh]);

  const switchProject = useCallback(
    (id: string) => {
      setError(null);
      setTree([]);
      setMeta(null);
      setActiveProject(id);
      // 이미 활성인 프로젝트를 다시 고르면 setActiveProject 가 무시돼 effect 가
      // 돌지 않는다. 방금 비운 meta/tree 가 그대로 남으므로 refresh 로 강제한다.
      setRefresh((n) => n + 1);
      navigate("/");
      api.activate(id).catch(() => undefined);
    },
    [navigate]
  );

  const runParse = useCallback(
    async (id: string) => {
      setError(null);
      setParsing(id);
      try {
        const { job } = await api.reparse(id);
        const done = await waitForJob(job);
        if (done.state === "failed") setError(done.error ?? "parse failed");
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setParsing(null);
        await loadProjects();
        setRefresh((n) => n + 1);
      }
    },
    [loadProjects]
  );

  const removeProject = useCallback(
    async (p: ProjectInfo) => {
      if (!confirm(t("removeConfirm", { name: p.name }))) return;
      await api.removeProject(p.id).catch((e) => setError(e.message));
      const r = await loadProjects();
      if (activeProject === p.id) switchProject(r?.active ?? "default");
    },
    [activeProject, loadProjects, switchProject, t]
  );

  useEffect(() => {
    if (meta && !langPinned && meta.language !== lang) setLangState(meta.language);
  }, [meta, langPinned, lang]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits(null);
      return;
    }
    const timer = setTimeout(() => {
      api
        .search(q)
        .then((r) => setHits(r.results))
        .catch((e) => setError(e.message));
    }, 200);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <LangContext.Provider value={langValue}>
      <div className="app">
        <aside className="sidebar">
          <div className="brand-row">
            <div className="brand" onClick={() => navigate("/")}>
              <span className="brand-mark">LW</span>
              <div>
                <div className="brand-title">{meta?.project ?? "LLMWiki"}</div>
                <div className="brand-sub">
                  {t("brandSub", {
                    programs: meta?.counts.programs ?? 0,
                    documents: meta?.counts.documents ?? 0,
                    tables: meta?.counts.tables ?? 0,
                  })}
                </div>
              </div>
            </div>
            <LangToggle lang={lang} onChange={setLang} />
          </div>

          <ProjectBar
            projects={projects}
            activeId={activeProject ?? ""}
            busy={parsing}
            onSwitch={switchProject}
            onOpenPicker={() => setPickerOpen(true)}
            onReparse={runParse}
            onRemove={removeProject}
          />

          <input
            className="search"
            placeholder={t("searchPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />

          {hits ? (
            <SearchResults hits={hits} onPick={(id) => navigate(`/p/${id}`)} />
          ) : (
            <Tree tree={tree} route={route} onPick={navigate} />
          )}

          <div className="side-actions">
            <button className="tables-link" onClick={() => navigate("/tables")}>
              {t("tablesLink")}
            </button>
            <button
              className="tables-link"
              onClick={() => {
                setSource(null);
                setBrowserOpen(true);
              }}
            >
              {t("sourceLink")}
            </button>
          </div>
        </aside>

        <main className="content">
          {error && <div className="banner error">{error}</div>}
          {route.kind === "home" && (
            <Home
              meta={meta}
              tree={tree}
              onPick={navigate}
              onOpenPicker={() => setPickerOpen(true)}
              onParse={() => activeProject && runParse(activeProject)}
            />
          )}
          {route.kind === "program" && (
            <ProgramView
              key={`${activeProject}:${route.id}:${refresh}`}
              id={route.id}
              meta={meta}
              onNavigate={navigate}
              onOpenSource={openSource}
              onGenerated={() => setRefresh((n) => n + 1)}
            />
          )}
          {route.kind === "tables" && <TablesView onPick={navigate} />}
          {route.kind === "table" && (
            <TableView name={route.name} onPick={navigate} onOpenSource={openSource} />
          )}
        </main>

        {browserOpen && (
          <SourceBrowser
            key={activeProject ?? ""}
            target={source}
            onClose={() => setBrowserOpen(false)}
          />
        )}

        {pickerOpen && (
          <FolderPicker
            onClose={() => setPickerOpen(false)}
            onOpened={async (id) => {
              setPickerOpen(false);
              await loadProjects();
              switchProject(id);
            }}
          />
        )}
      </div>
    </LangContext.Provider>
  );
}

function LangToggle({ lang, onChange }: { lang: Lang; onChange: (l: Lang) => void }) {
  return (
    <div className="lang-toggle" role="group" aria-label="Language">
      {LANGS.map((l) => (
        <button
          key={l}
          className={l === lang ? "active" : ""}
          onClick={() => onChange(l)}
          aria-pressed={l === lang}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function Tree({
  tree,
  route,
  onPick,
}: {
  tree: TreeLayer[];
  route: Route;
  onPick: (p: string) => void;
}) {
  const { t } = useLang();
  const activeId = route.kind === "program" ? route.id : null;
  return (
    <nav className="tree">
      {tree.map((layer) => (
        <div key={layer.layer} className="tree-layer">
          <div className="tree-layer-name">{layer.layer}</div>
          {layer.tiers.map((tier) => (
            <div key={tier.tier}>
              <div className="tree-tier">{tier.tier}</div>
              {tier.programs.map((p) => (
                <button
                  key={p.id}
                  className={`tree-item ${activeId === p.id ? "active" : ""}`}
                  onClick={() => onPick(`/p/${p.id}`)}
                  title={p.urls.join(", ")}
                >
                  <span className={`dot ${p.has_doc ? "ok" : "todo"}`} />
                  <span className="tree-item-name">{p.name}</span>
                  <span className="tree-item-badge">{p.sql_count}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      ))}
      {tree.length === 0 && <div className="muted">{t("noPrograms")}</div>}
    </nav>
  );
}

function SearchResults({
  hits,
  onPick,
}: {
  hits: SearchHit[];
  onPick: (id: string) => void;
}) {
  const { t } = useLang();
  if (hits.length === 0) return <div className="muted pad">{t("noResults")}</div>;
  return (
    <div className="hits">
      {hits.map((h) => (
        <button key={h.id} className="hit" onClick={() => onPick(h.id)}>
          <div className="hit-title">{h.name}</div>
          <div className="hit-meta">
            {h.layer}
            {h.matched.length > 0 && ` · ${h.matched.join(", ")}`}
          </div>
          <div className="hit-snippet">{h.snippet}</div>
        </button>
      ))}
    </div>
  );
}

function Home({
  meta,
  tree,
  onPick,
  onOpenPicker,
  onParse,
}: {
  meta: Meta | null;
  tree: TreeLayer[];
  onPick: (p: string) => void;
  onOpenPicker: () => void;
  onParse: () => void;
}) {
  const { t } = useLang();
  const all = useMemo(
    () =>
      tree.flatMap((l) =>
        l.tiers.flatMap((tier) => tier.programs.map((p) => ({ ...p, layer: l.layer })))
      ),
    [tree]
  );
  const missing = all.filter((p) => !p.has_doc);

  return (
    <div className="page">
      <h1>{meta?.project ?? "LLMWiki"}</h1>
      <p className="lede">{t("homeLede")}</p>

      <div className="stats">
        <Stat label={t("statPrograms")} value={meta?.counts.programs} />
        <Stat label={t("statDocuments")} value={meta?.counts.documents} />
        <Stat label={t("statClasses")} value={meta?.counts.classes} />
        <Stat label={t("statStatements")} value={meta?.counts.statements} />
        <Stat label={t("statTables")} value={meta?.counts.tables} />
      </div>

      {missing.length > 0 && (
        <div className="banner warn">
          {t("missingDocs", { count: missing.length })} <code>llmwiki generate</code>{" "}
          {t("missingDocsCmd")}
        </div>
      )}

      <h2>{t("programsHeading")}</h2>
      {all.length === 0 && <EmptyPrograms meta={meta} onOpenPicker={onOpenPicker} onParse={onParse} />}
      <div className="cards">
        {all.map((p) => (
          <button key={p.id} className="card" onClick={() => onPick(`/p/${p.id}`)}>
            <div className="card-layer">{p.layer}</div>
            <div className="card-title">{p.name}</div>
            <div className="card-urls">{p.urls.slice(0, 3).join("  ") || "—"}</div>
            <div className="card-tables">
              {p.tables.map((table) => (
                <span key={table} className="chip">
                  {table}
                </span>
              ))}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/** 프로그램이 0건일 때, 왜 0건인지까지 알려 준다. */
function EmptyPrograms({
  meta,
  onOpenPicker,
  onParse,
}: {
  meta: Meta | null;
  onOpenPicker: () => void;
  onParse: () => void;
}) {
  const { t } = useLang();
  const classes = meta?.counts.classes ?? 0;

  if (meta && !meta.parsed) {
    return (
      <div className="empty-state">
        <p className="muted">{t("notParsedYet")}</p>
        <button className="btn" onClick={onParse}>
          {t("runParse")}
        </button>
      </div>
    );
  }

  // Java 는 있는데 프로그램 단위가 안 나온 경우
  if (classes > 0) {
    return (
      <div className="empty-state">
        <p className="empty-title">{t("noProgramsFound", { classes })}</p>
        <p className="muted">{t("noProgramsHint")}</p>
        <button className="btn" onClick={onOpenPicker}>
          {t("openFolder")}
        </button>
      </div>
    );
  }

  // Java 자체가 없는 경우 — 무엇이 있었는지 보여 준다.
  // 이게 없으면 빈 목록만 남아 "아무 반응이 없다"로 읽힌다.
  const survey = meta?.survey;
  return (
    <div className="empty-state">
      <p className="empty-title">{t("noJavaTitle")}</p>
      {survey && (
        <>
          <p className="muted">{t("noJavaScanned", { files: survey.files })}</p>
          <div className="ext-row">
            {survey.by_ext.map((e) => (
              <span key={e.ext} className="chip">
                {e.ext} {e.count}
              </span>
            ))}
          </div>
          {survey.skipped_dirs.length > 0 && (
            <p className="muted small">
              {t("noJavaSkipped", { dirs: survey.skipped_dirs.join(", ") })}
            </p>
          )}
        </>
      )}
      <p className="muted">{t("noJavaScope")}</p>
      <p className="muted">{t("noJavaNext")}</p>
      <button className="btn" onClick={onOpenPicker}>
        {t("openFolder")}
      </button>
    </div>
  );
}

function Stat({ label, value }: { label: string; value?: number }) {
  return (
    <div className="stat">
      <div className="stat-value">{value ?? "–"}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

/** 명세서 생성 버튼 — 진행 상태와 오류를 자체적으로 들고 있다. */
/** 공급자가 준비 안 됐을 때 '무엇을 어떻게' 를 그대로 보여 준다. */
function ProviderWarning({ ready }: { ready?: Readiness }) {
  const { t } = useLang();
  if (!ready || ready.ok) return null;
  return (
    <div className="banner warn provider-warn">
      <strong>{t("providerNotReady")} — {ready.reason}</strong>
      <div className="provider-hint-label">{t("howToFix")}</div>
      <pre>{ready.hint}</pre>
    </div>
  );
}

/** 고른 공급자는 문서를 옮겨 다녀도 유지된다 — 매번 다시 고르게 하지 않는다. */
const PROVIDER_KEY = "llmwiki.provider";

/** 공급자 표시 이름. t 는 정적 키만 받으므로 여기서 갈라 준다.
 *  모르는 공급자(설정에 새로 추가된 것)는 id 를 그대로 보여 준다. */
function providerLabel(id: string, t: (k: StringKey) => string): string {
  if (id === "grok") return t("provider_grok");
  if (id === "ollama") return t("provider_ollama");
  if (id === "claude") return t("provider_claude");
  if (id === "template") return t("provider_template");
  return id;
}

function GenerateButton({
  id,
  label,
  onDone,
  ready,
}: {
  id: string;
  label: string;
  onDone: () => void;
  ready?: Readiness;
}) {
  const { t } = useLang();
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [list, setList] = useState<ProviderInfo[]>([]);
  const [picked, setPicked] = useState<string>(
    () => localStorage.getItem(PROVIDER_KEY) ?? ""
  );

  useEffect(() => {
    api
      .providers()
      .then((r) => {
        setList(r.providers);
        // 저장해 둔 선택이 지금 설정에 없으면(설정이 바뀐 경우) 기본값으로 되돌린다
        setPicked((prev) =>
          prev && r.providers.some((p) => p.id === prev) ? prev : r.default
        );
      })
      .catch(() => undefined);
  }, []);

  const choose = (value: string) => {
    setPicked(value);
    setErr(null);
    try {
      localStorage.setItem(PROVIDER_KEY, value);
    } catch {
      /* 저장 못 해도 이번 세션에서는 동작한다 */
    }
  };

  // 준비 상태는 '고른' 공급자를 따라야 한다. meta 의 것은 서버 기본값이라,
  // 사내 모델을 골라 놓고 외부 API 키가 없다는 경고를 보게 되면 안 된다.
  const current = list.find((p) => p.id === picked);
  const effective = current?.ready ?? ready;
  const blocked = effective ? !effective.ok : false;

  const run = async () => {
    setErr(null);
    try {
      const { job: jobId } = await api.generate(id, picked || undefined);
      const done = await waitForJob(jobId, setJob);
      setJob(null);
      if (done.state === "failed") setErr(done.error ?? t("generateFailed"));
      else onDone();
    } catch (e) {
      setJob(null);
      setErr((e as Error).message);
    }
  };

  return (
    <>
      <button
        className="btn"
        onClick={run}
        disabled={!!job || blocked}
        title={blocked ? effective?.reason : ""}
      >
        {job ? job.message || t("generating") : label}
      </button>

      {list.length > 1 && (
        <label className="prov-pick">
          <select
            value={picked}
            onChange={(e) => choose(e.target.value)}
            disabled={!!job}
          >
            {list.map((p) => (
              <option key={p.id} value={p.id}>
                {providerLabel(p.id, t)}
                {p.ready.ok ? "" : ` — ${t("providerUnavailable")}`}
              </option>
            ))}
          </select>
          {current && (
            <span className="prov-model" title={current.model}>
              {current.local ? t("providerLocalNote") : t("providerCloudNote")}
              {current.model ? ` · ${current.model}` : ""}
            </span>
          )}
        </label>
      )}

      {err && <div className="banner error">{err}</div>}
      <ProviderWarning ready={effective} />
    </>
  );
}

function ProgramView({
  id,
  meta,
  onNavigate,
  onOpenSource,
  onGenerated,
}: {
  id: string;
  meta: Meta | null;
  onNavigate: (p: string) => void;
  onOpenSource: (target: SourceTarget) => void;
  onGenerated: () => void;
}) {
  const { t } = useLang();
  const [doc, setDoc] = useState<DocResponse | null>(null);
  const [facts, setFacts] = useState<ProgramFacts | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setDoc(null);
    setFacts(null);
    setErr(null);
    api
      .doc(id)
      .then(setDoc)
      // 문서가 없으면 파서가 아는 사실만이라도 보여 주고 생성 버튼을 낸다
      .catch(() => api.programFacts(id).then(setFacts).catch((e) => setErr(e.message)));
  }, [id]);

  if (err) return <div className="page banner error">{err}</div>;

  if (facts) {
    return (
      <div className="page">
        <div className="crumb">{facts.layer}</div>
        <h1>{facts.name}</h1>
        <div className="doc-sub">
          <code>{facts.entry}</code>
        </div>

        <div className="banner warn">{t("noDocYet")}</div>
        <p className="lede">{t("noDocHint")}</p>
        <div className="gen-row">
          <GenerateButton
            id={id}
            label={t("generateDoc")}
            onDone={onGenerated}
            ready={meta?.provider_ready}
          />
        </div>

        <div className="pill-row">
          {facts.urls.map((u) => (
            <span key={u} className="pill url">{u}</span>
          ))}
          {facts.tables.map((table) => (
            <button key={table} className="pill table" onClick={() => onNavigate(`/t/${table}`)}>
              {table}
            </button>
          ))}
          <span className="pill">{t("sqlCount", { n: facts.sql_count })}</span>
        </div>

        <h2>{t("analyzedSources")}</h2>
        <div className="file-list">
          {facts.files.map((f) => (
            <button
              key={f}
              className="file"
              onClick={() => onOpenSource({ path: f })}
              title={t("openInBrowser")}
            >
              {f}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (!doc) return <div className="page muted">{t("loading")}</div>;

  const m = doc.meta;
  return (
    <div className="page">
      <div className="doc-head">
        <div>
          <div className="crumb">{m.layer}</div>
          <h1>{m.name}</h1>
          <div className="doc-sub">
            <code>{m.entry}</code>
            {m.generated_at && <span className="muted"> · {m.generated_at} · {m.generator}</span>}
          </div>
        </div>
        <div className="doc-actions">
          <GenerateButton
            id={id}
            label={t("regenerate")}
            onDone={onGenerated}
            ready={meta?.provider_ready}
          />
          <a className="btn" href={api.excelUrl(id)}>
            {t("excelDownload")}
          </a>
        </div>
      </div>

      <div className="pill-row">
        {(m.urls ?? []).map((u) => (
          <span key={u} className="pill url">
            {u}
          </span>
        ))}
        {(m.tables ?? []).map((table) => (
          <button key={table} className="pill table" onClick={() => onNavigate(`/t/${table}`)}>
            {table}
          </button>
        ))}
      </div>

      <Markdown source={doc.markdown} onNavigate={onNavigate} />

      <h2>{t("analyzedSources")}</h2>
      <div className="file-list">
        {(m.files ?? []).map((f) => (
          <button
            key={f}
            className="file"
            onClick={() => onOpenSource({ path: f })}
            title={t("openInBrowser")}
          >
            {f}
          </button>
        ))}
      </div>
    </div>
  );
}

function TablesView({ onPick }: { onPick: (p: string) => void }) {
  const { t } = useLang();
  const [rows, setRows] = useState<{ name: string; crud: string[]; programs: string[] }[]>([]);
  useEffect(() => {
    api.tables().then(setRows).catch(() => setRows([]));
  }, []);
  return (
    <div className="page">
      <h1>{t("tablesTitle")}</h1>
      <p className="lede">{t("tablesLede")}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("colTable")}</th>
              <th>C</th>
              <th>R</th>
              <th>U</th>
              <th>D</th>
              <th>{t("colUsedBy")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>
                  <button className="linkish" onClick={() => onPick(`/t/${r.name}`)}>
                    {r.name}
                  </button>
                </td>
                {["C", "R", "U", "D"].map((op) => (
                  <td key={op} className="center">
                    {r.crud.includes(op) ? "●" : ""}
                  </td>
                ))}
                <td>{r.programs.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TableView({
  name,
  onPick,
  onOpenSource,
}: {
  name: string;
  onPick: (p: string) => void;
  onOpenSource: (target: SourceTarget) => void;
}) {
  const { t } = useLang();
  const [detail, setDetail] = useState<TableDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setDetail(null);
    setErr(null);
    api.table(name).then(setDetail).catch((e) => setErr(e.message));
  }, [name]);

  if (err) return <div className="page banner error">{err}</div>;
  if (!detail) return <div className="page muted">{t("loading")}</div>;

  return (
    <div className="page">
      <div className="crumb">{t("crumbTable")}</div>
      <h1>{detail.name}</h1>
      <div className="pill-row">
        {detail.crud.map((c) => (
          <span key={c} className="pill">
            {c}
          </span>
        ))}
      </div>

      <h2>{t("affectedPrograms")}</h2>
      <div className="cards">
        {detail.programs.map((p) => (
          <button key={p.id} className="card" onClick={() => onPick(`/p/${p.id}`)}>
            <div className="card-layer">{p.layer}</div>
            <div className="card-title">{p.name}</div>
          </button>
        ))}
      </div>

      <h2>{t("sqlUsingTable")}</h2>
      {detail.statements.map((s) => (
        <div key={s.id} className="sql-card">
          <div className="sql-head">
            <code>{s.id}</code>
            <span className={`tag ${s.kind}`}>{s.kind}</span>
            <button
              className="linkish"
              onClick={() => onOpenSource({ path: s.path })}
              title={t("openInBrowser")}
            >
              {s.path}
            </button>
          </div>
          <pre>
            <code>{s.sql}</code>
          </pre>
        </div>
      ))}
    </div>
  );
}
