import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  setApiLang,
  type DocResponse,
  type Meta,
  type SearchHit,
  type TableDetail,
  type TreeLayer,
} from "./api";
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

  // 저장된 선택이 없으면 config.yaml 의 output.language 를 따른다 (/api/meta 응답).
  const [lang, setLangState] = useState<Lang>(() => readStoredLang() ?? "ko");
  const [langPinned, setLangPinned] = useState(() => readStoredLang() !== null);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    setLangPinned(true);
    storeLang(next);
  }, []);

  // 렌더 중에 맞춰 둔다. 자식의 effect 가 부모보다 먼저 도는 탓에,
  // effect 안에서 바꾸면 첫 요청이 이전 언어로 나갈 수 있다.
  setApiLang(lang);

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

  // 언어가 바뀌면 서버 메시지도 그 언어로 다시 받는다.
  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(e.message));
    api.tree().then(setTree).catch((e) => setError(e.message));
  }, [lang]);

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
          {route.kind === "home" && <Home meta={meta} tree={tree} onPick={navigate} />}
          {route.kind === "program" && (
            <ProgramView id={route.id} onNavigate={navigate} onOpenSource={openSource} />
          )}
          {route.kind === "tables" && <TablesView onPick={navigate} />}
          {route.kind === "table" && (
            <TableView name={route.name} onPick={navigate} onOpenSource={openSource} />
          )}
        </main>

        {browserOpen && (
          <SourceBrowser target={source} onClose={() => setBrowserOpen(false)} />
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
}: {
  meta: Meta | null;
  tree: TreeLayer[];
  onPick: (p: string) => void;
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

function Stat({ label, value }: { label: string; value?: number }) {
  return (
    <div className="stat">
      <div className="stat-value">{value ?? "–"}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function ProgramView({
  id,
  onNavigate,
  onOpenSource,
}: {
  id: string;
  onNavigate: (p: string) => void;
  onOpenSource: (target: SourceTarget) => void;
}) {
  const { t } = useLang();
  const [doc, setDoc] = useState<DocResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setDoc(null);
    setErr(null);
    api.doc(id).then(setDoc).catch((e) => setErr(e.message));
  }, [id]);

  if (err) return <div className="page banner error">{err}</div>;
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
        <a className="btn" href={api.excelUrl(id)}>
          {t("excelDownload")}
        </a>
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
