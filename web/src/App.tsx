import { useCallback, useEffect, useMemo, useState } from "react";
import { api,
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
  type TreeLayer, type WikiHealth } from "./api";
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
import Compliance, { REG_TABS, type RegTab } from "./Compliance";
import Operations from "./Operations";
import { ServiceDashboard, ServiceNav } from "./Services";
import KnowledgeBase, { KB_TABS, type KbTab } from "./KnowledgeBase";
import Wiki, { WIKI_TABS, type WikiTab } from "./Wiki";
import WikiAdmin, { ADMIN_TABS, type AdminTab } from "./WikiAdmin";
import EngineBar, { EngineLayer } from "./EngineBar";
import WikiStatusBoard from "./WikiStatusBoard";
import LlmPicker from "./LlmPicker";
import { VISIBLE_SOLUTIONS, menuOwning, menusFor, solution, solutionOf, solutionsFor,
         type SolutionCode, type SolutionMenu } from "./solutions";
import { ROLES, clearWho, readRole, readWho, role as roleOf, storeRole, storeWho,
         type RoleCode } from "./roles";
import Login from "./Login";
import RolePick from "./RolePick";
import {
  NgAdmin, NgChat, NgDocView, NgForecast, NgGov, NgInsights,
  NgKnowledgeDb, NgMonitor, NgRag, NgSection, NgSlm,
} from "./NanoGrid";

type Route =
  | { kind: "home" }
  | { kind: "program"; id: string }
  | { kind: "table"; name: string }
  | { kind: "tables" }
  | { kind: "data" }
  | { kind: "reg"; tab: RegTab }
  // 서비스 축은 /reg 와 다른 경로에 둔다 — 조직 단위 현황과 서비스 단위 작업이
  // 한 줄에 놓여 있으면 순서가 생기지 않는다.
  | { kind: "svc"; id: string }
  | { kind: "kb"; tab: KbTab }
  | { kind: "wiki"; tab: WikiTab }
  | { kind: "admin"; tab: AdminTab }
  | { kind: "ng-monitor"; tab: "energy" | "ev" | "events" }
  | { kind: "ng-forecast" }
  | { kind: "ng-knowledge" }
  | { kind: "ng-insights" }
  | { kind: "ng-admin" }
  | { kind: "ng-gov" }
  | { kind: "ng-chat" }
  | { kind: "ng-slm" }
  | { kind: "ng-rag" }
  | { kind: "ng-doc"; id: string }
  | { kind: "engines" };

/** 나노그리드 화면의 현재 경로 (NgSection 활성 표시용). 다른 솔루션이면 "". */
function ngRoutePath(route: Route): string {
  switch (route.kind) {
    case "ng-monitor":
      return route.tab === "energy" ? "/ng/monitor" : `/ng/monitor/${route.tab}`;
    case "ng-forecast": return "/ng/forecast";
    case "ng-knowledge": return "/ng/knowledge";
    case "ng-insights": return "/ng/insights";
    case "ng-admin": return "/ng/admin";
    case "ng-gov": return "/ng/gov";
    case "ng-chat": return "/ng/learn/chat";
    case "ng-slm": return "/ng/learn/slm";
    case "ng-rag": return "/ng/learn/rag";
    case "ng-doc": return `/ng/doc/${route.id}`;
    default: return "";
  }
}

/** 사이드바 메뉴가 지금 화면을 가리키는가.
 *
 *  경로만 보면 한 화면의 탭을 각각 메뉴로 낸 경우(`/kb` 와 `/kb/checklist`)에
 *  둘 다 활성으로 보인다. 메뉴가 맡는 탭이 지정돼 있으면 탭까지 맞춰 본다. */
/** 사이드바 메뉴에 붙일 상태 칩.
 *
 *  가이드 02 — 메뉴를 '기능 이름 목록' 이 아니라 '지금 어디까지 왔는가' 로 읽히게
 *  한다. 색만으로 말하지 않도록(가이드 04 접근성) 아이콘과 글자를 함께 낸다. */
type MenuStatus = { tone: "ok" | "review" | "idle"; text: string };

function useMenuStatus(): Record<string, MenuStatus | undefined> {
  const [health, setHealth] = useState<WikiHealth | null>(null);
  const [checklists, setChecklists] = useState<number | null>(null);

  useEffect(() => {
    api.wiki.health().then(setHealth).catch(() => setHealth(null));
    api.audit.checklists().then((r) => setChecklists(r.checklists.length)).catch(() => setChecklists(null));
  }, []);

  if (!health) return {};
  const pages = health.store.pages;
  const unverified = pages - health.store.numeric_verified;
  const drafts = health.store.by_status.draft ?? 0;

  return {
    wiki: { tone: pages > 0 ? "ok" : "idle", text: `${pages}장` },
    review: drafts > 0
      ? { tone: "review", text: `${drafts}건 대기` }
      : { tone: "ok", text: "승인 완료" },
    checklist: checklists === null
      ? undefined
      : checklists > 0
        ? { tone: "ok", text: `${checklists}건` }
        : { tone: "idle", text: "없음" },
    // 검산 불일치는 위키 메뉴가 아니라 관리자에서 처리한다 — 여기 두면 두 곳이 같은
    // 숫자를 다르게 말한다.
    ...(unverified > 0 ? {} : {}),
  };
}

function menuActive(m: SolutionMenu, route: Route): boolean {
  // 서비스 대시보드(/svc/<id>)는 경로가 /reg 가 아니지만 같은 축이다.
  if (route.kind === "svc") return m.tabs?.includes("services") ?? false;
  if (route.kind !== m.match.slice(1)) return false;
  if (!m.tabs) return true;
  const tab = (route as { tab?: string }).tab;
  return tab !== undefined && m.tabs.includes(tab);
}

/** 앱이 하위 경로에 얹혀 있을 수 있다 (게이트웨이 뒤 `/aigov/` 등).
 *
 * 라우팅을 `location.pathname` 그대로 하면 그런 배포에서 전부 첫 화면으로 떨어진다.
 * 주소창의 경로에서 접두사를 떼어 앱 경로로 바꾸고, 되돌릴 때 다시 붙인다.
 * api.ts 도 같은 `BASE_URL` 을 쓰므로 정적·API·라우팅이 한 접두사를 공유한다. */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

/** 주소창 경로 → 앱 경로 */
function appPath(pathname: string): string {
  if (BASE && pathname.startsWith(BASE)) return pathname.slice(BASE.length) || "/";
  return pathname;
}

/** 앱 경로 → 주소창 경로 */
function fullPath(path: string): string {
  return `${BASE}${path}`;
}

function parseRoute(path: string): Route {
  // 첫 화면은 규제 서비스 목록이다. 이 제품이 무엇을 하는 도구인지 들어오자마자
  // 말해야 하고, 규제 작업의 출발점은 조직 현황이 아니라 서비스 하나다.
  // 프로그램 목록은 사라지지 않고 /programs 로 옮겼다.
  if (path === "/" || path === "") return { kind: "reg", tab: "overview" };
  if (path === "/programs") return { kind: "home" };
  if (path.startsWith("/p/")) return { kind: "program", id: path.slice(3) };
  if (path.startsWith("/t/")) return { kind: "table", name: decodeURIComponent(path.slice(3)) };
  if (path === "/tables") return { kind: "tables" };
  // 데이터 분석은 소스 분석과 같은 축이다 — 둘 다 운영 자산의 사실이다.
  if (path === "/data") return { kind: "data" };
  // 나노그리드 데이터 지식화 (/ng/*)
  if (path === "/ng/monitor") return { kind: "ng-monitor", tab: "energy" };
  if (path === "/ng/monitor/ev") return { kind: "ng-monitor", tab: "ev" };
  if (path === "/ng/monitor/events") return { kind: "ng-monitor", tab: "events" };
  if (path === "/ng/forecast") return { kind: "ng-forecast" };
  if (path === "/ng/knowledge") return { kind: "ng-knowledge" };
  if (path === "/ng/insights") return { kind: "ng-insights" };
  if (path === "/ng/admin") return { kind: "ng-admin" };
  if (path === "/ng/gov") return { kind: "ng-gov" };
  if (path === "/ng/learn/chat") return { kind: "ng-chat" };
  if (path === "/ng/learn/slm" || path === "/ng/learn") return { kind: "ng-slm" };
  if (path === "/ng/learn/rag") return { kind: "ng-rag" };
  if (path.startsWith("/ng/doc/")) return { kind: "ng-doc", id: path.slice(8) };
  if (path.startsWith("/svc/")) return { kind: "svc", id: decodeURIComponent(path.slice(5)) };
  if (path.startsWith("/reg")) {
    const tab = path.slice(5) as RegTab;
    return { kind: "reg", tab: REG_TABS.includes(tab) ? tab : "assess" };
  }
  if (path.startsWith("/kb")) {
    const tab = path.slice(4) as KbTab;
    return { kind: "kb", tab: KB_TABS.includes(tab) ? tab : "analyze" };
  }
  // 위키 열람과 관리자는 경로를 나눈다. 열람만 필요한 사람에게 업로드·검증 화면을
  // 보여 주지 않는 것이 접근 통제의 첫 단계다.
  if (path.startsWith("/wiki")) {
    const tab = path.slice(6) as WikiTab;
    return { kind: "wiki", tab: WIKI_TABS.includes(tab) ? tab : "browse" };
  }
  if (path.startsWith("/admin")) {
    const tab = path.slice(7) as AdminTab;
    return { kind: "admin", tab: ADMIN_TABS.includes(tab) ? tab : "upload" };
  }
  // 엔진 레이어는 어느 솔루션에도 속하지 않는다 — 둘이 공유하는 바닥이다.
  if (path === "/engines") return { kind: "engines" };
  return { kind: "home" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(appPath(location.pathname)));
  // 역할 — 회의 피드백("너무 많고 복잡하다")에 대한 답. 자기 일과 상관없는
  // 메뉴를 접어 둔다. 접근 통제가 아니라 보기 필터다.
  const [roleCode, setRoleCode] = useState<RoleCode>(readRole);
  // 로그인한 사람. 비어 있으면 로그인 화면을 낸다. SSO 가 붙으면 이 값이
  // 포털에서 내려오고 이 화면은 사라진다.
  const [who, setWho] = useState<string>(readWho);
  // 로그인 직후에는 역할을 한 번 묻는다. 계정에 붙은 역할을 미리 골라 두되,
  // 한 사람이 기획도 하고 운영도 보는 조직이 많아 바꿀 수 있게 둔다.
  // 이미 들어와 있던 사람(저장된 who)에게는 묻지 않는다 — 새로 고칠 때마다
  // 같은 것을 묻는 화면은 금방 눈에서 지워진다.
  const [pickRole, setPickRole] = useState<{ role: RoleCode; remember: boolean } | null>(null);
  const menuStatus = useMenuStatus();
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

  // 솔루션은 별도 상태로 들지 않는다 — 주소창으로 바로 들어온 사람과 메뉴로
  // 들어온 사람이 다른 화면을 보면 안 된다.
  const activeSolution: SolutionCode = solutionOf(
    route.kind === "engines" ? "/engines" : appPath(location.pathname)
  );

  // 지금 보는 화면이 이 역할의 메뉴에 없는가. 있으면 그 메뉴를 돌려준다.
  const hiddenHere = useMemo(() => {
    const owning = menuOwning((m) => menuActive(m, route));
    return owning?.roles && !owning.roles.includes(roleCode) ? owning : null;
  }, [route, roleCode]);

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
    history.pushState(null, "", fullPath(path));
    setRoute(parseRoute(path));
  }, []);

  const openSource = useCallback((target: SourceTarget) => {
    setSource(target);
    setBrowserOpen(true);
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(appPath(location.pathname)));
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
      navigate("/programs");
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

  // ★ 여기서 분기한다. 위의 훅이 전부 불린 뒤라야 훅 순서가 유지된다 —
  //   조건부로 일찍 return 하면 렌더마다 훅 개수가 달라져 React 가 깨진다.
  if (!who) {
    return (
      <LangContext.Provider value={langValue}>
        <Login
          base={BASE}
          lang={lang}
          setLang={setLang}
          onEnter={(name, picked, remember) => {
            setWho(name);
            setRoleCode(picked);
            // 아직 저장하지 않는다. 다음 화면에서 역할을 고른 뒤에 함께 남긴다.
            setPickRole({ role: picked, remember });
          }}
        />
      </LangContext.Provider>
    );
  }

  // 로그인 다음, 화면에 들어가기 전에 역할을 한 번 묻는다.
  if (pickRole) {
    return (
      <LangContext.Provider value={langValue}>
        <RolePick
          base={BASE}
          who={who}
          accountRole={pickRole.role}
          onBack={() => {
            // 잘못 들어왔을 때 되돌아가는 길. 아무것도 저장하지 않았으므로
            // 로그인 화면으로 그냥 돌아간다.
            setPickRole(null);
            setWho("");
            clearWho();
          }}
          onPick={(picked) => {
            setRoleCode(picked);
            // "로그인 상태 유지" 를 껐으면 저장하지 않는다 — 새로 고치면
            // 다시 묻는다. 켰을 때만 브라우저에 남긴다.
            if (pickRole.remember) {
              storeWho(who);
              storeRole(picked);
            }
            setPickRole(null);
          }}
        />
      </LangContext.Provider>
    );
  }

  return (
    <LangContext.Provider value={langValue}>
      <div className="app">
        <aside className="sidebar">
          <div className="brand-row">
            <div className="brand" onClick={() => navigate("/")}>
              <img src={`${BASE}/gng-logo.png`} alt="GnG" className="brand-logo" />
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

          {/* 솔루션 전환 — 대상과 사용자가 다른 두 작업 공간을 가른다.
              한 사이드바에 여섯 개를 늘어놓으면 '테이블 목록' 옆에 '위키 관리자'가
              붙어, 처음 보는 사람은 이게 한 흐름인 줄 안다. */}
          <div className="solution-switch">
            {solutionsFor(VISIBLE_SOLUTIONS, roleCode).map((sol) => (
              <button
                key={sol.code}
                className={`solution-tab ${activeSolution === sol.code ? "active" : ""}`}
                onClick={() => navigate(sol.home)}
              >
                <span className="solution-name">{t(sol.labelKey)}</span>
                <span className="solution-tagline">{t(sol.taglineKey)}</span>
              </button>
            ))}
          </div>

          {activeSolution === "code" ? (
            <>
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
                <button
                  className={`tables-link ${route.kind === "tables" || route.kind === "table" ? "active" : ""}`}
                  onClick={() => navigate("/tables")}
                >
                  {t("tablesLink")}
                </button>
                {/* 데이터 분석 — 코드와 같은 축이다. 코드가 무엇을 만지는지와
                    그 데이터가 어떤 상태인지는 함께 봐야 판단이 된다. */}
                <button
                  className={`tables-link ${route.kind === "data" ? "active" : ""}`}
                  onClick={() => navigate("/data")}
                >
                  {t("dataLink")}
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
            </>
          ) : activeSolution === "compliance" ? (
            <>
              {/* 규제 그래프는 프로젝트 단위가 아니라 조직 전체에 하나뿐이다.
                  그래서 여기에는 프로젝트 선택도, 프로그램 트리도 없다. */}
              <nav className="solution-menu">
                {menusFor(solution("compliance"), roleCode).map((m) => (
                  <button
                    key={m.path}
                    className={`solution-item ${menuActive(m, route) ? "active" : ""}`}
                    onClick={() => navigate(m.path)}
                  >
                    <span className="solution-item-head">
                      {m.step !== undefined && (
                        <span className="solution-step" aria-hidden>{m.step}</span>
                      )}
                      <span className="solution-item-label">{t(m.labelKey)}</span>
                    </span>
                    <span className="solution-item-desc">{t(m.descKey)}</span>
                  </button>
                ))}
              </nav>

              <ServiceNav
                activeUuid={route.kind === "svc" ? route.id : null}
                onPick={navigate}
              />
            </>
          ) : activeSolution === "nanogrid" ? (
            <>
              {/* ② 데이터 구축 — 모니터링·예측. 세부 메뉴는 NgSection 이 그린다. */}
              <NgSection activePath={ngRoutePath(route)} onPick={navigate} mode="data" />
            </>
          ) : activeSolution === "learn" ? (
            <nav className="solution-menu">
              {/* ④ LLM 학습 (기획 v0.2) — 순서가 곧 파이프라인: CES → 대화 축적 → 검색 근거 */}
              {menusFor(solution("learn"), roleCode).map((m) => (
                <button
                  key={m.path}
                  className={`solution-item ${menuActive(m, route) ? "active" : ""}`}
                  onClick={() => navigate(m.path)}
                >
                  <span className="solution-item-head">
                    {m.step !== undefined && (
                      <span className="solution-step" aria-hidden>{m.step}</span>
                    )}
                    <span className="solution-item-label">{t(m.labelKey)}</span>
                  </span>
                  <span className="solution-item-desc">{t(m.descKey)}</span>
                </button>
              ))}
            </nav>
          ) : (
            <>
              {/* 보고서 지식화는 프로젝트 단위가 아니다 — 업종과 사업장이 분리 축이라
                  좌측 트리(소스 분석)와 성격이 다르다. */}
              <nav className="solution-menu">
                {menusFor(solution("report"), roleCode).map((m) => {
                  const st = m.statusKey ? menuStatus[m.statusKey] : undefined;
                  return (
                    <button
                      key={m.path}
                      className={`solution-item ${menuActive(m, route) ? "active" : ""}`}
                      onClick={() => navigate(m.path)}
                    >
                      <span className="solution-item-head">
                        {m.step !== undefined && (
                          <span className="solution-step" aria-hidden>{m.step}</span>
                        )}
                        <span className="solution-item-label">{t(m.labelKey)}</span>
                        {st && (
                          <span className={`menu-chip ${st.tone}`}>
                            <span aria-hidden>{st.tone === "ok" ? "●" : st.tone === "review" ? "▲" : "○"}</span>
                            {st.text}
                          </span>
                        )}
                      </span>
                      <span className="solution-item-desc">{t(m.descKey)}</span>
                    </button>
                  );
                })}
              </nav>

              {/* 사내/외부 LLM 선택은 화면 하나가 아니라 **솔루션 전체**에 걸린다.
                  적재와 초안 제안이 각자 공급자를 들고 있으면 한쪽은 사내로 다른
                  쪽은 사외로 나가는데, 사용자는 한 번 골랐다고 믿는다. */}
              <LlmPicker />

              {/* 생성·검산·배포를 **따로** 보여 준다. 하나로 합치면 '위키는 잘
                  만들어졌는데 원문 수치가 어긋난' 상태를 표현할 수 없다. */}
              <WikiStatusBoard onNavigate={navigate} compact />
            </>
          )}

          <EngineBar onOpen={() => navigate("/engines")} />
        </aside>

        <main className="content">
          {/* 역할 — 지금은 사람이 고르지만, 사내 포털과 연동되면 로그인 권한에서
              내려온다. 그때 이 자리는 '고르는 곳' 이 아니라 '내가 누구인지 보는
              곳' 이 된다. 그래서 화면 맨 위, 항상 보이는 자리에 둔다. */}
          <div className="topbar">
            <span className="topbar-role">
              <label htmlFor="role-pick">{t("roleTitle")}</label>
              <select
                id="role-pick"
                value={roleCode}
                onChange={(e) => {
                  const next = e.target.value as RoleCode;
                  setRoleCode(next);
                  storeRole(next);
                }}
              >
                {ROLES.map((r) => (
                  <option key={r.code} value={r.code}>{t(r.labelKey)}</option>
                ))}
              </select>
            </span>
            <span className="topbar-desc">{t(roleOf(roleCode).descKey)}</span>
            <span className="topbar-note">{t("roleFilterNote")}</span>
            {/* 누구로 들어와 있는지. SSO 가 붙으면 여기에 사번·부서가 온다. */}
            <span className="topbar-who">
              <b>{who}</b>
              <button
                className="linkish"
                onClick={() => {
                  clearWho();
                  setWho("");
                }}
              >
                {t("lgLeave")}
              </button>
            </span>
          </div>

          {/* 역할이 감춘 화면에 주소로 바로 들어왔을 때. 메뉴에 없는 이유를
              말해 주지 않으면 "바뀐 게 없다" 로 읽힌다 — 실제로 그런 일이 있었다. */}
          {hiddenHere && (
            <div className="banner note topbar-hidden">
              {t("roleHiddenHere")
                .replace("{roles}", hiddenHere.roles!.map((r) => t(roleOf(r).labelKey)).join(" · "))
                .replace("{now}", t(roleOf(roleCode).labelKey))}
            </div>
          )}
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
          {route.kind === "reg" && (
            <Compliance tab={route.tab} roleCode={roleCode} onNavigate={navigate} />
          )}
          {route.kind === "svc" && (
            <ServiceDashboard key={route.id} uuid={route.id} onNavigate={navigate} />
          )}
          {route.kind === "kb" && (
            <KnowledgeBase
              tab={route.tab}
              onTab={(tab) => navigate(tab === "analyze" ? "/kb" : `/kb/${tab}`)}
            />
          )}
          {route.kind === "wiki" && (
            <Wiki
              tab={route.tab}
              onTab={(tab) => navigate(tab === "browse" ? "/wiki" : `/wiki/${tab}`)}
            />
          )}
          {route.kind === "admin" && (
            <WikiAdmin
              tab={route.tab}
              onTab={(tab) => navigate(tab === "upload" ? "/admin" : `/admin/${tab}`)}
            />
          )}
          {route.kind === "data" && <Operations onNavigate={navigate} />}
          {route.kind === "engines" && <EngineLayer onNavigate={navigate} />}
          {route.kind === "ng-monitor" && <NgMonitor tab={route.tab} onNavigate={navigate} />}
          {route.kind === "ng-forecast" && <NgForecast />}
          {route.kind === "ng-knowledge" && <NgKnowledgeDb />}
          {route.kind === "ng-insights" && <NgInsights onNavigate={navigate} />}
          {route.kind === "ng-admin" && <NgAdmin onNavigate={navigate} />}
          {route.kind === "ng-gov" && <NgGov />}
          {route.kind === "ng-chat" && <NgChat onNavigate={navigate} />}
          {route.kind === "ng-slm" && <NgSlm onNavigate={navigate} />}
          {route.kind === "ng-rag" && <NgRag onNavigate={navigate} />}
          {route.kind === "ng-doc" && <NgDocView id={route.id} onNavigate={navigate} />}
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
