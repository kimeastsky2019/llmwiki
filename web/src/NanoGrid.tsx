/**
 * NanoGrid AI System — llmwiki portal integration.
 *
 * Sidebar mode tabs:
 *   [Source Analysis]  ops source → specs · compliance (project, search, source tree, AI-Gov)
 *   [Data Knowledge]   data → knowledge base · wiki (monitoring, forecast, knowledge DB, insights, admin)
 *
 * All labels are bilingual (ko/en) and follow the portal's KO/EN toggle (useLang).
 * Data flows through same-origin /api/ng/* (llmwiki server proxies to ngwiki).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area, CartesianGrid, ComposedChart, Legend, Line,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import Markdown from "./Markdown";
import { useLang, type Lang } from "./i18n";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

const fmt = (v: number | null | undefined, suffix = "", digits = 1) =>
  v === null || v === undefined ? "—" : `${Number(v).toFixed(digits)}${suffix}`;

const localeOf = (lang: Lang) => (lang === "en" ? "en-US" : "ko-KR");

const timeOf = (ts: string, lang: Lang) =>
  new Date(ts).toLocaleTimeString(localeOf(lang), { hour: "2-digit", minute: "2-digit" });

const dateTimeOf = (ts: string | null | undefined, lang: Lang) =>
  ts ? new Date(ts).toLocaleString(localeOf(lang)) : "—";

/** Bilingual literal helper. */
type L2 = { ko: string; en: string };
const pick = (lang: Lang, s: L2) => (lang === "en" ? s.en : s.ko);

function useTr() {
  const { lang } = useLang();
  return {
    lang,
    tr: (ko: string, en: string) => (lang === "en" ? en : ko),
  };
}

/* --------------------------------------------------------------- palette */
// 검증된 범주 팔레트 (validate_palette.js PASS, light surface):
// 의미가 색을 정한다 — 수요=blue, 발전=orange, 배터리=aqua, EV=violet, 계통=red/yellow.
const C = {
  cons: "#2a78d6",
  gen: "#eb6834",
  batt: "#1baf7a",
  ev: "#4a3aa7",
  gridImp: "#e34948",
  gridExp: "#eda100",
  ink: "#0f172a",
  muted: "#64748b",
  track: "#e2e8f0",
  ok: "#008300",
  warn: "#eda100",
};

/* ------------------------------------------------------- infographic bits */

/** 라디얼 게이지(도넛) — 단일 값의 비율 표현. 중앙에 수치, 아래에 라벨. */
function Donut({
  value, max = 100, size = 88, stroke = 10, color = C.cons,
  text, sub,
}: {
  value: number | null | undefined; max?: number; size?: number; stroke?: number;
  color?: string; text?: string; sub?: string;
}) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const frac = value == null ? 0 : Math.max(0, Math.min(1, value / max));
  return (
    <div className="ng-donut" style={{ width: size }}>
      <svg width={size} height={size} role="img" aria-label={`${text ?? value}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={C.track} strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${frac * circ} ${circ}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle"
          fontSize={size / 5} fontWeight={700} fill={C.ink}>
          {text ?? (value == null ? "—" : `${Math.round(value)}%`)}
        </text>
      </svg>
      {sub && <div className="ng-donut-sub">{sub}</div>}
    </div>
  );
}

/** 에너지 흐름 개요도 — PV/풍력·계통·배터리·건물부하·EV 사이의 실시간 전력 흐름. */
function EnergyFlowDiagram({
  kpi, ev, lang, tr,
}: {
  kpi: KpiData | null; ev: EvData | null; lang: Lang;
  tr: (ko: string, en: string) => string;
}) {
  const gen = kpi?.now.generation_kw ?? 0;
  const cons = kpi?.now.consumption_kw ?? 0;
  const battP = kpi?.now.battery_power_kw ?? 0;      // +방전 / -충전
  const soc = kpi?.now.battery_soc_pct ?? null;
  const imp = Math.max(0, cons + Math.max(0, -battP) + (ev?.summary.total_power_kw ?? 0) - gen - Math.max(0, battP));
  const evP = ev?.summary.total_power_kw ?? 0;
  const exp = Math.max(0, gen + Math.max(0, battP) - cons - Math.max(0, -battP) - evP);

  const W = 880, H = 320;
  const hub = { x: W / 2, y: H / 2 };

  // 흐름 두께: 2px 바닥 + kW 비례 (상한 10px)
  const w = (kw: number) => (kw > 0.05 ? Math.min(10, 2 + kw / 8) : 0);

  interface Flow { from: [number, number]; to: [number, number]; kw: number; color: string }
  const nodes = {
    pv: { x: 120, y: 62, icon: "☀️", label: tr("태양광·풍력", "Solar & Wind"), kw: gen, color: C.gen },
    grid: { x: 120, y: 256, icon: "🏭", label: tr("전력 계통", "Grid"), kw: imp > 0.05 ? imp : exp, color: imp > 0.05 ? C.gridImp : C.gridExp },
    load: { x: W - 120, y: 62, icon: "🏢", label: tr("건물 부하", "Building Load"), kw: cons, color: C.cons },
    evn: { x: W - 120, y: 256, icon: "🔌", label: tr("EV 충전기", "EV Chargers"), kw: evP, color: C.ev },
    batt: { x: W / 2, y: H - 46, icon: "🔋", label: tr("배터리", "Battery"), kw: Math.abs(battP), color: C.batt },
  };
  const flows: Flow[] = [
    { from: [nodes.pv.x + 70, nodes.pv.y], to: [hub.x - 46, hub.y - 14], kw: gen, color: C.gen },
    ...(imp > 0.05
      ? [{ from: [nodes.grid.x + 70, nodes.grid.y], to: [hub.x - 46, hub.y + 14], kw: imp, color: C.gridImp } as Flow]
      : [{ from: [hub.x - 46, hub.y + 14], to: [nodes.grid.x + 70, nodes.grid.y], kw: exp, color: C.gridExp } as Flow]),
    { from: [hub.x + 46, hub.y - 14], to: [nodes.load.x - 70, nodes.load.y], kw: cons, color: C.cons },
    { from: [hub.x + 46, hub.y + 14], to: [nodes.evn.x - 70, nodes.evn.y], kw: evP, color: C.ev },
    ...(battP >= 0
      ? [{ from: [hub.x, nodes.batt.y - 26], to: [hub.x, hub.y + 26], kw: battP, color: C.batt } as Flow]
      : [{ from: [hub.x, hub.y + 26], to: [hub.x, nodes.batt.y - 26], kw: -battP, color: C.batt } as Flow]),
  ];

  const locale = localeOf(lang);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ng-flow" role="img"
      aria-label={tr("에너지 흐름 개요도", "Energy flow overview")}>
      {/* 흐름선 (곡선 + 이동 대시 애니메이션) */}
      {flows.map((f, i) => {
        const sw = w(f.kw);
        const mx = (f.from[0] + f.to[0]) / 2;
        const d = `M ${f.from[0]} ${f.from[1]} C ${mx} ${f.from[1]}, ${mx} ${f.to[1]}, ${f.to[0]} ${f.to[1]}`;
        return (
          <g key={i}>
            <path d={d} fill="none" stroke={sw ? f.color : C.track}
              strokeOpacity={sw ? 0.25 : 0.6} strokeWidth={sw || 2} />
            {sw > 0 && (
              <path d={d} fill="none" stroke={f.color} strokeWidth={sw}
                strokeLinecap="round" className="ng-flow-dash" />
            )}
            {sw > 0 && (
              <text
                x={f.from[0] === f.to[0] ? mx + 40 : mx}
                y={(f.from[1] + f.to[1]) / 2 - (f.from[0] === f.to[0] ? -4 : 8)}
                textAnchor="middle" fontSize="12" fontWeight={600} fill={f.color}>
                {f.kw.toLocaleString(locale, { maximumFractionDigits: 1 })} kW
              </text>
            )}
          </g>
        );
      })}

      {/* 허브 */}
      <g>
        <circle cx={hub.x} cy={hub.y} r={34} fill="#fff" stroke={C.ink} strokeWidth={2} />
        <text x={hub.x} y={hub.y - 5} textAnchor="middle" fontSize="15">⚡</text>
        <text x={hub.x} y={hub.y + 13} textAnchor="middle" fontSize="10" fontWeight={700} fill={C.ink}>
          {tr("나노그리드", "NanoGrid")}
        </text>
      </g>

      {/* 노드 */}
      {Object.entries(nodes).map(([k, n]) => (
        <g key={k}>
          <rect x={n.x - 70} y={n.y - 26} width={140} height={52} rx={10}
            fill="#fff" stroke={n.kw > 0.05 ? n.color : C.track} strokeWidth={2} />
          <text x={n.x - 56} y={n.y + 1} fontSize="16">{n.icon}</text>
          <text x={n.x - 34} y={n.y - 6} fontSize="11" fill={C.muted}>{n.label}</text>
          <text x={n.x - 34} y={n.y + 12} fontSize="14" fontWeight={700} fill={C.ink}>
            {k === "batt" && soc != null
              ? `${n.kw.toFixed(1)} kW · ${soc.toFixed(0)}%`
              : `${n.kw.toFixed(1)} kW`}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** 지식 파이프라인 개요도 — 수집→저장→예측/문서화→위키. */
function PipelineDiagram({
  counts, lang, tr,
}: {
  counts: Record<string, number>; lang: Lang;
  tr: (ko: string, en: string) => string;
}) {
  const W = 940, H = 240;
  const n = (v: number | undefined) => Number(v ?? 0).toLocaleString(localeOf(lang));
  const boxes = [
    { x: 20, y: 88, w: 130, icon: "📡", title: tr("SP-G / 시뮬레이터", "SP-G / Simulator"), sub: tr("실측 15분", "15-min data"), color: C.muted },
    { x: 200, y: 88, w: 130, icon: "⚙️", title: "ingest", sub: tr("수집·이벤트", "collect · events"), color: C.cons },
    { x: 380, y: 88, w: 150, icon: "🗄", title: "TimescaleDB", sub: `${n(counts.measurements)} pts`, color: C.ink },
    { x: 590, y: 24, w: 140, icon: "📈", title: "forecast-svc", sub: `${n(counts.experiments)} ${tr("실험", "runs")}`, color: C.gen },
    { x: 590, y: 152, w: 140, icon: "🧠", title: "insight-worker", sub: `${n(counts.insight_docs)} ${tr("문서", "docs")}`, color: C.batt },
    { x: 790, y: 88, w: 130, icon: "📚", title: tr("지식 위키", "Knowledge Wiki"), sub: tr("검색·통찰", "search · insight"), color: C.ev },
  ];
  const cy = (b: (typeof boxes)[number]) => b.y + 32;
  const arrows: [number, number][][] = [
    [[boxes[0].x + boxes[0].w, cy(boxes[0])], [boxes[1].x, cy(boxes[1])]],
    [[boxes[1].x + boxes[1].w, cy(boxes[1])], [boxes[2].x, cy(boxes[2])]],
    [[boxes[2].x + boxes[2].w, cy(boxes[2]) - 8], [boxes[3].x, cy(boxes[3])]],
    [[boxes[2].x + boxes[2].w, cy(boxes[2]) + 8], [boxes[4].x, cy(boxes[4])]],
    [[boxes[3].x + boxes[3].w, cy(boxes[3])], [boxes[5].x, cy(boxes[5]) - 8]],
    [[boxes[4].x + boxes[4].w, cy(boxes[4])], [boxes[5].x, cy(boxes[5]) + 8]],
  ];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ng-flow" role="img"
      aria-label={tr("지식 파이프라인 개요도", "Knowledge pipeline overview")}>
      <defs>
        <marker id="ng-arrow" viewBox="0 0 8 8" refX="7" refY="4"
          markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L8 4 L0 8 z" fill={C.muted} />
        </marker>
      </defs>
      {arrows.map(([[x1, y1], [x2, y2]], i) => {
        const mx = (x1 + x2) / 2;
        return (
          <path key={i} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2 - 4} ${y2}`}
            fill="none" stroke={C.muted} strokeWidth={1.6} markerEnd="url(#ng-arrow)" />
        );
      })}
      {boxes.map((b) => (
        <g key={b.title}>
          <rect x={b.x} y={b.y} width={b.w} height={64} rx={10}
            fill="#fff" stroke={b.color} strokeWidth={2} />
          <text x={b.x + 12} y={b.y + 26} fontSize="15">{b.icon}</text>
          <text x={b.x + 34} y={b.y + 27} fontSize="12" fontWeight={700} fill={C.ink}>{b.title}</text>
          <text x={b.x + 12} y={b.y + 48} fontSize="11" fill={C.muted}>{b.sub}</text>
        </g>
      ))}
      <text x={boxes[2].x + boxes[2].w / 2} y={boxes[2].y + 84} textAnchor="middle"
        fontSize="11" fill={C.muted}>
        {tr("사실은 SQL이 · 서술은 LLM이", "Facts from SQL · narrative from LLM")}
      </text>
    </svg>
  );
}

/* ------------------------------------------------------------------ types */

interface WikiDocMeta {
  doc_id: string;
  title: string;
  llm_provider?: string;
  period_start?: string;
  updated_at?: string;
}

interface WikiGroup { type: string; label: string; count: number; docs: WikiDocMeta[] }

const DOC_TYPE_LABELS: Record<string, L2> = {
  daily: { ko: "일간 운영 브리프", en: "Daily Operations Brief" },
  weekly: { ko: "주간 성능 리포트", en: "Weekly Performance Report" },
  event: { ko: "이상 이벤트 노트", en: "Anomaly Event Notes" },
};

const docTypeLabel = (lang: Lang, type: string, fallback: string) =>
  DOC_TYPE_LABELS[type] ? pick(lang, DOC_TYPE_LABELS[type]) : fallback;

/* -------------------------------------------------------- sidebar section */

interface MenuChild { path: string; label: L2 }
interface MenuItem { path: string; label: L2; icon: string; children?: MenuChild[] }
interface MenuGroup { title: L2; gov?: boolean; items: MenuItem[] }

const MENU: MenuGroup[] = [
  {
    title: { ko: "나노그리드 운영", en: "NanoGrid Operations" },
    items: [
      {
        path: "/ng/monitor", icon: "⚡",
        label: { ko: "실시간 모니터링", en: "Real-time Monitoring" },
        children: [
          { path: "/ng/monitor", label: { ko: "에너지 개요", en: "Energy Overview" } },
          { path: "/ng/monitor/ev", label: { ko: "EV 충전기", en: "EV Chargers" } },
          { path: "/ng/monitor/events", label: { ko: "이상 이벤트", en: "Anomaly Events" } },
        ],
      },
      { path: "/ng/forecast", icon: "📈", label: { ko: "시계열 예측 랩", en: "Forecast Lab" } },
    ],
  },
  {
    title: { ko: "지식 데이터베이스", en: "Knowledge Database" },
    items: [
      { path: "/ng/knowledge", icon: "🗄", label: { ko: "지식 DB 구축", en: "Knowledge DB Build" } },
      { path: "/ng/insights", icon: "🧠", label: { ko: "지식과 통찰", en: "Knowledge & Insights" } },
      { path: "/ng/admin", icon: "⚙", label: { ko: "Wiki 관리자", en: "Wiki Admin" } },
    ],
  },
  {
    title: { ko: "AI-Gov 규제준수", en: "AI-Gov Compliance" },
    gov: true,
    items: [
      { path: "/ng/gov", icon: "📜", label: { ko: "법률 분석·체크리스트", en: "Law Analysis · Checklist" } },
    ],
  },
];

/* ------------------------------------------------- sidebar mode tabs ---- */

export type NgMode = "source" | "data";

/** Mode forced by the current route. null = keep current mode (e.g. home). */
export function ngModeForPath(path: string): NgMode | null {
  if (path.startsWith("/ng/gov")) return "source";        // compliance lives in Source Analysis
  if (path.startsWith("/ng/")) return "data";
  if (path.startsWith("/p/") || path.startsWith("/t/") || path === "/tables") return "source";
  return null;
}

const MODE_TABS: { key: NgMode; title: L2; sub: L2 }[] = [
  {
    key: "source",
    title: { ko: "소스 분석", en: "Source Analysis" },
    sub: { ko: "운영 소스 → 명세서 · 규제 준수", en: "Ops source → specs · compliance" },
  },
  {
    key: "data",
    title: { ko: "데이터 지식화", en: "Data Knowledge" },
    sub: { ko: "데이터 → 지식베이스 · 위키", en: "Data → knowledge base · wiki" },
  },
];

export function NgModeTabs({
  mode,
  onChange,
}: {
  mode: NgMode;
  onChange: (m: NgMode) => void;
}) {
  const { lang } = useTr();
  return (
    <div className="ng-mode-tabs">
      {MODE_TABS.map((t) => (
        <button
          key={t.key}
          className={`ng-mode-tab ${mode === t.key ? "active" : ""}`}
          onClick={() => onChange(t.key)}
        >
          <div className="ng-mode-title">{pick(lang, t.title)}</div>
          <div className="ng-mode-sub">{pick(lang, t.sub)}</div>
        </button>
      ))}
    </div>
  );
}

export function NgProjectSelect() {
  const { tr } = useTr();
  return (
    <div className="ng-project">
      <span className="ng-project-label">{tr("프로젝트", "Project")}</span>
      <select defaultValue="nanogrid">
        <option value="nanogrid">nanogrid_AI_management_system</option>
      </select>
    </div>
  );
}

export function NgSection({
  activePath,
  onPick,
  mode = "data",
}: {
  activePath: string;
  onPick: (p: string) => void;
  mode?: NgMode;
}) {
  const { lang } = useTr();

  const isActive = (p: string) => activePath === p;
  const inSubtree = (item: MenuItem) =>
    activePath === item.path || activePath.startsWith(item.path + "/");

  // Source Analysis tab shows only AI-Gov; Data Knowledge tab shows the rest.
  const visible = MENU.filter((g) => (mode === "source" ? g.gov : !g.gov));

  return (
    <div className="ng-section">
      {visible.map((g) => (
        <div key={g.title.ko} className="tree-layer">
          <div className="tree-layer-name">{pick(lang, g.title)}</div>
          {g.items.map((m) => (
            <div key={m.path}>
              <button
                className={`tree-item ${isActive(m.path) ? "active" : ""}`}
                onClick={() => onPick(m.path)}
              >
                <span className="ng-icon">{m.icon}</span>
                <span className="tree-item-name">{pick(lang, m.label)}</span>
              </button>
              {m.children && inSubtree(m) && (
                <div className="ng-children">
                  {m.children.map((c) => (
                    <button
                      key={c.path}
                      className={`tree-item ng-doc ${isActive(c.path) ? "active" : ""}`}
                      onClick={() => onPick(c.path)}
                    >
                      <span className="tree-item-name">{pick(lang, c.label)}</span>
                    </button>
                  ))}
                </div>
              )}
              {/* 인사이트 문서는 날짜 드롭 대신 '지식과 통찰' 페이지의 날짜 검색으로 찾는다 */}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- monitor */

interface KpiData {
  now: {
    ts: string; generation_kw: number; consumption_kw: number;
    battery_soc_pct: number | null; battery_power_kw: number;
  };
  today: { gen_kwh: number | null; cons_kwh: number | null };
  self_consumption_pct: number | null;
  self_sufficiency_pct: number | null;
}

interface TsPoint {
  ts: string; generation_kw: number; consumption_kw: number;
  forecast_generation_kw: number | null; forecast_consumption_kw: number | null;
}

interface NgEvent { id: number; ts: string; severity: string; title: string; detail?: string }

interface EvCharger {
  id: number; name: string; connector: string; max_kw: number;
  status: string; power_kw: number; session_kwh: number;
  session_started_at: string | null; today_kwh: number; today_sessions: number;
}

interface EvData {
  chargers: EvCharger[];
  summary: {
    total: number; charging: number; fault: number;
    total_power_kw: number; today_kwh: number; today_sessions: number;
  };
}

const EV_STATUS: Record<string, { label: L2; cls: string }> = {
  idle: { label: { ko: "대기", en: "Idle" }, cls: "ng-ev-idle" },
  charging: { label: { ko: "충전 중", en: "Charging" }, cls: "ng-ev-charging" },
  finishing: { label: { ko: "충전 완료 대기", en: "Finishing" }, cls: "ng-ev-finishing" },
  fault: { label: { ko: "고장", en: "Fault" }, cls: "ng-ev-fault" },
};

export function NgMonitor({
  tab,
  onNavigate,
}: {
  tab: "energy" | "ev" | "events";
  onNavigate: (p: string) => void;
}) {
  const { lang, tr } = useTr();
  const [kpi, setKpi] = useState<KpiData | null>(null);
  const [points, setPoints] = useState<TsPoint[]>([]);
  const [events, setEvents] = useState<NgEvent[]>([]);
  const [latest, setLatest] = useState<WikiDocMeta[]>([]);
  const [ev, setEv] = useState<EvData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [k, ts, evts, docs, evd] = await Promise.all([
        getJson<KpiData>("/api/ng/kpi"),
        getJson<{ points: TsPoint[] }>("/api/ng/timeseries?hours=24"),
        getJson<NgEvent[]>("/api/ng/events?limit=15"),
        getJson<WikiDocMeta[]>(`/api/ng/wiki/latest?limit=3&lang=${lang}`),
        getJson<EvData>("/api/ng/ev"),
      ]);
      setKpi(k); setPoints(ts.points); setEvents(evts); setLatest(docs); setEv(evd);
      setError(null);
    } catch (e) { setError(String(e)); }
  }, [lang]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, [refresh]);

  const data = useMemo(
    () => points.map((p) => ({ ...p, time: timeOf(p.ts, lang) })),
    [points, lang],
  );

  if (error)
    return (
      <div className="banner error">
        {tr("나노그리드 지식위키 서버 연결 실패", "Failed to reach the NanoGrid knowledge-wiki server")} — {error}
      </div>
    );

  const cards: {
    label: string; value: string; sub: string;
    donut?: { value: number | null; color: string };
  }[] = [
    { label: tr("현재 발전", "Generation"), value: fmt(kpi?.now.generation_kw, " kW"), sub: `${tr("금일", "Today")} ${fmt(kpi?.today.gen_kwh, " kWh")}` },
    { label: tr("현재 소비", "Consumption"), value: fmt(kpi?.now.consumption_kw, " kW"), sub: `${tr("금일", "Today")} ${fmt(kpi?.today.cons_kwh, " kWh")}` },
    { label: tr("배터리 SoC", "Battery SoC"), value: fmt(kpi?.now.battery_soc_pct, "%"), sub: `${(kpi?.now.battery_power_kw ?? 0) >= 0 ? tr("방전", "Discharging") : tr("충전", "Charging")} ${fmt(Math.abs(kpi?.now.battery_power_kw ?? 0), " kW")}`,
      donut: { value: kpi?.now.battery_soc_pct ?? null, color: C.batt } },
    { label: tr("자가소비율", "Self-consumption"), value: fmt(kpi?.self_consumption_pct, "%"), sub: `${tr("자립률", "Self-sufficiency")} ${fmt(kpi?.self_sufficiency_pct, "%")}`,
      donut: { value: kpi?.self_consumption_pct ?? null, color: C.gen } },
    { label: tr("EV 충전", "EV Charging"), value: fmt(ev?.summary.total_power_kw, " kW"), sub: `${tr("충전 중", "Active")} ${ev?.summary.charging ?? 0}/${ev?.summary.total ?? 0} · ${tr("금일", "Today")} ${fmt(ev?.summary.today_kwh, " kWh")}` },
  ];

  const SUB = [
    { key: "energy", path: "/ng/monitor", label: tr("에너지 개요", "Energy Overview") },
    { key: "ev", path: "/ng/monitor/ev", label: `${tr("EV 충전기", "EV Chargers")} (${ev?.summary.charging ?? 0} ${tr("충전 중", "charging")})` },
    { key: "events", path: "/ng/monitor/events", label: `${tr("이상 이벤트", "Anomaly Events")} (${events.length})` },
  ] as const;

  return (
    <div className="ng-page">
      <h1 className="ng-title">⚡ {tr("나노그리드 실시간 모니터링", "NanoGrid Real-time Monitoring")}</h1>
      <p className="muted">
        {tr("TimescaleDB(ng.*) 실측 + day-ahead 예측 · 15초 자동 갱신",
            "TimescaleDB (ng.*) measurements + day-ahead forecast · refreshes every 15s")}
      </p>

      <div className="ng-kpis">
        {cards.map((c) => (
          <div key={c.label} className="ng-kpi ng-kpi-row">
            <div>
              <div className="ng-kpi-label">{c.label}</div>
              <div className="ng-kpi-value">{c.value}</div>
              <div className="ng-kpi-sub">{c.sub}</div>
            </div>
            {c.donut && (
              <Donut value={c.donut.value} color={c.donut.color} size={56} stroke={7} />
            )}
          </div>
        ))}
      </div>

      <div className="ng-subtabs">
        {SUB.map((s) => (
          <button
            key={s.key}
            className={`ng-subtab ${tab === s.key ? "active" : ""}`}
            onClick={() => onNavigate(s.path)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {tab === "energy" && (
        <>
          <div className="ng-panel">
            <div className="ng-panel-title">
              🗺 {tr("에너지 흐름 개요도 — 실시간", "Energy Flow Overview — Live")}
            </div>
            <EnergyFlowDiagram kpi={kpi} ev={ev} lang={lang} tr={tr} />
          </div>

          <div className="ng-panel">
            <div className="ng-panel-title">
              {tr("최근 24시간 — 발전/소비 실측 · 예측 오버레이",
                  "Last 24 hours — generation/consumption with forecast overlay")}
            </div>
            <div style={{ height: 300 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="time" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} unit=" kW" />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area dataKey="generation_kw" name={tr("발전(실측)", "Generation (actual)")} stroke={C.gen} strokeWidth={2} fill={C.gen} fillOpacity={0.16} />
                  <Area dataKey="consumption_kw" name={tr("소비(실측)", "Consumption (actual)")} stroke={C.cons} strokeWidth={2} fill={C.cons} fillOpacity={0.14} />
                  <Line dataKey="forecast_generation_kw" name={tr("발전(예측)", "Generation (forecast)")} stroke={C.gen} strokeDasharray="5 3" dot={false} />
                  <Line dataKey="forecast_consumption_kw" name={tr("소비(예측)", "Consumption (forecast)")} stroke={C.cons} strokeDasharray="5 3" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="ng-panel">
            <div className="ng-panel-title">🧠 {tr("최신 AI 인사이트", "Latest AI Insights")}</div>
            {latest.length === 0 && <div className="muted">{tr("아직 생성된 인사이트가 없습니다.", "No insights generated yet.")}</div>}
            {latest.map((d) => (
              <button key={d.doc_id} className="ng-doc-link" onClick={() => onNavigate(`/ng/doc/${d.doc_id}`)}>
                <div className="ng-doc-link-title">{d.title}</div>
                <div className="ng-doc-link-meta">{d.doc_id}</div>
              </button>
            ))}
          </div>
        </>
      )}

      {tab === "ev" && ev && (
        <div className="ng-panel">
          <div className="ng-panel-title">
            {tr("EV 충전기 현황", "EV Charger Status")} — {tr("금일", "Today")} {ev.summary.today_sessions} {tr("세션", "sessions")} · {fmt(ev.summary.today_kwh, " kWh")}
            {ev.summary.fault > 0 && (
              <span className="ng-sev ng-sev-critical" style={{ marginLeft: 8 }}>
                {tr("고장", "Fault")} {ev.summary.fault}
              </span>
            )}
          </div>
          <div className="ng-ev-grid">
            {ev.chargers.map((c) => {
              const st = EV_STATUS[c.status] ?? EV_STATUS.idle;
              return (
                <div key={c.id} className={`ng-ev-card ${st.cls}`}>
                  <div className="ng-ev-head">
                    <span className="ng-ev-name">🔌 {c.name}</span>
                    <span className="ng-ev-status">{pick(lang, st.label)}</span>
                  </div>
                  <div className="ng-ev-power">{fmt(c.power_kw, " kW")}<span className="muted"> / {fmt(c.max_kw, " kW", 0)} ({c.connector})</span></div>
                  <div className="ng-ev-bar">
                    <div className="ng-ev-bar-fill" style={{ width: `${Math.min(100, (c.power_kw / c.max_kw) * 100)}%` }} />
                  </div>
                  <div className="ng-kpi-sub">
                    {tr("현재 세션", "Current session")} {fmt(c.session_kwh, " kWh")}
                    {c.session_started_at ? ` · ${tr("시작", "started")} ${timeOf(c.session_started_at, lang)}` : ""}
                  </div>
                  <div className="ng-kpi-sub">{tr("금일", "Today")} {c.today_sessions} {tr("세션", "sessions")} · {fmt(c.today_kwh, " kWh")}</div>
                </div>
              );
            })}
          </div>
          <p className="muted" style={{ marginTop: 8 }}>
            {tr("※ 현재 시뮬레이션 상태 — P5에서 OCPP/실계측 수집기가 같은 테이블(ng.ev_chargers)을 갱신합니다.",
                "※ Simulated for now — in P5 an OCPP/field collector will update the same table (ng.ev_chargers).")}
          </p>
        </div>
      )}

      {tab === "events" && (
        <div className="ng-panel">
          <div className="ng-panel-title">{tr("이상 이벤트", "Anomaly Events")}</div>
          {events.length === 0 && <div className="muted">{tr("이상 없음", "No anomalies")}</div>}
          {events.map((e) => (
            <div key={e.id} className="ng-event">
              <span className={`ng-sev ng-sev-${e.severity}`}>{e.severity}</span>
              <span>{e.title}</span>
              {e.detail && <span className="muted">— {e.detail}</span>}
              <span className="ng-doc-link-meta">{dateTimeOf(e.ts, lang)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- forecast */

interface RunResult {
  model: string; target: string;
  metrics: { mape_pct: number | null; rmse: number; mae: number; n: number };
  series: { ts: string; actual: number; predicted: number }[];
}

interface Experiment {
  id: number; target: string; model: string; created_at: string;
  metrics_json: { mape_pct: number | null; rmse: number };
}

const TARGET_LABELS: Record<string, L2> = {
  consumption_kw: { ko: "수요(소비 전력)", en: "Demand (consumption)" },
  generation_kw: { ko: "발전량", en: "Generation" },
  temp_c: { ko: "온도", en: "Temperature" },
};

const targetLabel = (lang: Lang, key: string) =>
  TARGET_LABELS[key] ? pick(lang, TARGET_LABELS[key]) : key;

export function NgForecast() {
  const { lang, tr } = useTr();
  const [models, setModels] = useState<{ key: string; label: string }[]>([]);
  const [target, setTarget] = useState("consumption_kw");
  const [model, setModel] = useState("seasonal_naive_24h");
  const [trainDays, setTrainDays] = useState("14");
  const [testHours, setTestHours] = useState("24");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [ranking, setRanking] = useState<{ model: string; metrics: RunResult["metrics"] }[] | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadExperiments = useCallback(() => {
    getJson<Experiment[]>("/api/ng/forecast/experiments?limit=12")
      .then(setExperiments).catch(() => {});
  }, []);

  useEffect(() => {
    getJson<{ key: string; label: string }[]>("/api/ng/forecast/models")
      .then(setModels).catch((e) => setError(String(e)));
    loadExperiments();
  }, [loadExperiments]);

  const run = async () => {
    setRunning(true); setError(null); setRanking(null);
    try {
      setResult(await postJson<RunResult>("/api/ng/forecast/run", {
        target, model, train_days: Number(trainDays), test_hours: Number(testHours),
      }));
      loadExperiments();
    } catch (e) { setError(String(e)); } finally { setRunning(false); }
  };

  const selectBest = async () => {
    setRunning(true); setError(null);
    try {
      const r = await postJson<{ ranking: { model: string; metrics: RunResult["metrics"] }[]; best: string }>(
        "/api/ng/forecast/select_best",
        { target, train_days: Number(trainDays), test_hours: Number(testHours) },
      );
      setRanking(r.ranking);
      if (r.best) setModel(r.best);
      loadExperiments();
    } catch (e) { setError(String(e)); } finally { setRunning(false); }
  };

  const data = useMemo(
    () => (result?.series ?? []).map((p) => ({ ...p, time: timeOf(p.ts, lang) })),
    [result, lang],
  );
  const mapeOk = result?.metrics.mape_pct != null && result.metrics.mape_pct <= 10;

  return (
    <div className="ng-page">
      <h1 className="ng-title">📈 {tr("시계열 예측 랩", "Time-series Forecast Lab")}</h1>
      <p className="muted">
        {tr("학습 → 예측 → 평가 → 최적 모델 선택 · 실험은 ng.forecast_experiments 에 기록되어 'MAPE ≤ 10%' 실증 증거가 됩니다",
            "Train → predict → evaluate → select best · every run is recorded in ng.forecast_experiments as evidence for the 'MAPE ≤ 10%' target")}
      </p>

      <div className="ng-panel ng-form">
        <label>{tr("예측 대상", "Target")}
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {Object.keys(TARGET_LABELS).map((k) => (
              <option key={k} value={k}>{targetLabel(lang, k)}</option>
            ))}
          </select>
        </label>
        <label>{tr("모델", "Model")}
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        </label>
        <label>{tr("학습 기간(일)", "Train days")}
          <input value={trainDays} onChange={(e) => setTrainDays(e.target.value)} />
        </label>
        <label>{tr("평가 구간(시간)", "Test hours")}
          <input value={testHours} onChange={(e) => setTestHours(e.target.value)} />
        </label>
        <button className="ng-btn primary" onClick={run} disabled={running}>
          {running ? tr("실행 중…", "Running…") : tr("실험 실행", "Run Experiment")}
        </button>
        <button className="ng-btn" onClick={selectBest} disabled={running}>
          {tr("최적 모델 선택", "Select Best Model")}
        </button>
      </div>

      {error && <div className="banner error">{error}</div>}

      {result && (
        <div className="ng-cols">
          <div className="ng-panel" style={{ flex: 2 }}>
            <div className="ng-panel-title">
              {tr("예측 vs 실측", "Forecast vs Actual")} — {targetLabel(lang, result.target)} · {result.model}
            </div>
            <div style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="time" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line dataKey="actual" name={tr("실측", "Actual")} stroke={C.cons} dot={false} strokeWidth={2} />
                  <Line dataKey="predicted" name={tr("예측", "Forecast")} stroke={C.gen} strokeDasharray="5 3" dot={false} strokeWidth={2} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="ng-panel">
            <div className="ng-panel-title">{tr("평가 지표", "Metrics")}</div>
            <div className={`ng-mape ${mapeOk ? "ok" : "warn"}`}
              style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <Donut value={result.metrics.mape_pct} max={20} size={84} stroke={10}
                color={mapeOk ? C.ok : C.warn}
                text={fmt(result.metrics.mape_pct, "%", 1)} />
              <div>
                <div className="ng-kpi-label">{tr("MAPE (목표 ≤ 10%)", "MAPE (target ≤ 10%)")}</div>
                <div className="ng-kpi-sub" style={{ fontWeight: 600 }}>
                  {mapeOk ? `✅ ${tr("성능지표 충족", "Target met")}` : `⚠️ ${tr("성능지표 미충족", "Target not met")}`}
                </div>
              </div>
            </div>
            <table className="ng-table">
              <tbody>
                <tr><td>RMSE</td><td>{fmt(result.metrics.rmse, "", 3)}</td></tr>
                <tr><td>MAE</td><td>{fmt(result.metrics.mae, "", 3)}</td></tr>
                <tr><td>{tr("표본 수", "Samples")}</td><td>{result.metrics.n}</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {ranking && (
        <div className="ng-panel">
          <div className="ng-panel-title">{tr("모델 랭킹 (MAPE 오름차순)", "Model Ranking (MAPE ascending)")}</div>
          <table className="ng-table">
            <thead><tr><th>{tr("순위", "Rank")}</th><th>{tr("모델", "Model")}</th><th>MAPE %</th><th>RMSE</th></tr></thead>
            <tbody>
              {ranking.map((r, i) => (
                <tr key={r.model} className={i === 0 ? "best" : ""}>
                  <td>{i + 1}</td><td>{r.model}</td>
                  <td>{fmt(r.metrics.mape_pct, "", 2)}</td>
                  <td>{fmt(r.metrics.rmse, "", 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="ng-panel">
        <div className="ng-panel-title">{tr("실험 이력", "Experiment History")}</div>
        {experiments.length === 0 && <div className="muted">{tr("실험 이력이 없습니다.", "No experiments yet.")}</div>}
        {experiments.length > 0 && (
          <table className="ng-table">
            <thead><tr><th>#</th><th>{tr("대상", "Target")}</th><th>{tr("모델", "Model")}</th><th>MAPE %</th><th>RMSE</th><th>{tr("실행 시각", "Run at")}</th></tr></thead>
            <tbody>
              {experiments.map((e) => (
                <tr key={e.id}>
                  <td>{e.id}</td>
                  <td>{targetLabel(lang, e.target)}</td>
                  <td>{e.model}</td>
                  <td>{fmt(e.metrics_json?.mape_pct, "", 2)}</td>
                  <td>{fmt(e.metrics_json?.rmse, "", 3)}</td>
                  <td className="muted">{dateTimeOf(e.created_at, lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------- knowledge DB status */

interface Pipeline {
  counts: Record<string, number>;
  latest: Record<string, string | null>;
  quality_24h: { points: number; expected: number; missing_pct: number; avg_gen_kw: number | null; avg_cons_kw: number | null };
  docs_by_type: { doc_type: string; n: number; latest: string }[];
  principle: string;
}

const COUNT_LABELS: Record<string, L2> = {
  measurements: { ko: "실측 포인트", en: "Measurement points" },
  forecasts: { ko: "예측 포인트", en: "Forecast points" },
  events: { ko: "이벤트", en: "Events" },
  insight_docs: { ko: "인사이트 문서", en: "Insight documents" },
  experiments: { ko: "예측 실험", en: "Forecast experiments" },
  ev_chargers: { ko: "EV 충전기", en: "EV chargers" },
  gov_documents: { ko: "법률 문서", en: "Law documents" },
  gov_items: { ko: "준수 체크 항목", en: "Compliance items" },
};

export function NgKnowledgeDb() {
  const { lang, tr } = useTr();
  const [p, setP] = useState<Pipeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<Pipeline>("/api/ng/admin/pipeline").then(setP).catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="banner error">{error}</div>;
  if (!p) return <div className="muted pad">{tr("불러오는 중…", "Loading…")}</div>;

  return (
    <div className="ng-page">
      <h1 className="ng-title">🗄 {tr("지식 데이터베이스 구축", "Knowledge Database Build")}</h1>
      <p className="muted">
        {tr("수집(ingest) → 예측(forecast) → 문서화(insight) 파이프라인이 쌓아 올린 지식 계층 현황 · 사실은 SQL이, 서술은 LLM이 — facts_json 원본이 모든 문서에 보존됩니다",
            "Status of the knowledge layers built by the ingest → forecast → insight pipeline · facts come from SQL, narrative from the LLM — the original facts_json is preserved with every document")}
      </p>

      <div className="ng-panel">
        <div className="ng-panel-title">🗺 {tr("지식 파이프라인 개요도", "Knowledge Pipeline Overview")}</div>
        <PipelineDiagram counts={p.counts} lang={lang} tr={tr} />
      </div>

      <div className="ng-kpis">
        {Object.entries(p.counts).map(([k, v]) => (
          <div key={k} className="ng-kpi">
            <div className="ng-kpi-label">{COUNT_LABELS[k] ? pick(lang, COUNT_LABELS[k]) : k}</div>
            <div className="ng-kpi-value">{Number(v).toLocaleString()}</div>
          </div>
        ))}
      </div>

      <div className="ng-cols">
        <div className="ng-panel">
          <div className="ng-panel-title">{tr("파이프라인 최신 상태", "Pipeline Latest Status")}</div>
          <table className="ng-table">
            <tbody>
              <tr><td>{tr("마지막 실측 수집", "Last measurement")}</td><td>{dateTimeOf(p.latest.last_measurement, lang)}</td></tr>
              <tr><td>{tr("마지막 예측 기록", "Last forecast")}</td><td>{dateTimeOf(p.latest.last_forecast, lang)}</td></tr>
              <tr><td>{tr("마지막 인사이트 발행", "Last insight published")}</td><td>{dateTimeOf(p.latest.last_doc, lang)}</td></tr>
              <tr><td>{tr("마지막 예측 실험", "Last experiment")}</td><td>{dateTimeOf(p.latest.last_experiment, lang)}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="ng-panel">
          <div className="ng-panel-title">{tr("최근 24시간 데이터 품질", "Data Quality (last 24h)")}</div>
          <div className={`ng-mape ${p.quality_24h.missing_pct <= 2 ? "ok" : "warn"}`}
            style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <Donut value={100 - p.quality_24h.missing_pct} size={84} stroke={10}
              color={p.quality_24h.missing_pct <= 2 ? C.ok : C.warn}
              text={`${(100 - p.quality_24h.missing_pct).toFixed(1)}%`} />
            <div>
              <div className="ng-kpi-label">{tr("수집 완전성 (15분 해상도)", "Collection completeness (15-min)")}</div>
              <div className="ng-kpi-sub">
                {p.quality_24h.points} / {p.quality_24h.expected} {tr("포인트", "points")} ·{" "}
                {tr("결측", "missing")} {fmt(p.quality_24h.missing_pct, "%")}
              </div>
            </div>
          </div>
          <table className="ng-table">
            <tbody>
              <tr><td>{tr("24h 평균 발전", "24h avg generation")}</td><td>{fmt(p.quality_24h.avg_gen_kw, " kW", 2)}</td></tr>
              <tr><td>{tr("24h 평균 소비", "24h avg consumption")}</td><td>{fmt(p.quality_24h.avg_cons_kw, " kW", 2)}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="ng-panel">
        <div className="ng-panel-title">{tr("문서 계층 (지식 축적)", "Document Layer (accumulated knowledge)")}</div>
        <table className="ng-table">
          <thead><tr><th>{tr("문서 유형", "Document type")}</th><th>{tr("건수", "Count")}</th><th>{tr("최신", "Latest")}</th></tr></thead>
          <tbody>
            {p.docs_by_type.map((d) => (
              <tr key={d.doc_type}>
                <td>{docTypeLabel(lang, d.doc_type, d.doc_type)}</td>
                <td>{d.n}</td>
                <td className="muted">{dateTimeOf(d.latest, lang)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- insights */

/** ISO 주차 문자열 (weekly doc_id 용): 2026-W34 */
function isoWeekOf(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  const t = new Date(d.valueOf());
  t.setDate(t.getDate() + 3 - ((t.getDay() + 6) % 7));  // 해당 주의 목요일
  const week1 = new Date(t.getFullYear(), 0, 4);
  const week = 1 + Math.round(
    ((t.valueOf() - week1.valueOf()) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
  return `${t.getFullYear()}-W${String(week).padStart(2, "0")}`;
}

export function NgInsights({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { lang, tr } = useTr();
  const [groups, setGroups] = useState<WikiGroup[]>([]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<WikiDocMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [docType, setDocType] = useState<"daily" | "weekly">("daily");
  const [date, setDate] = useState(() => new Date(Date.now() - 86400000).toISOString().slice(0, 10));
  const [dateMsg, setDateMsg] = useState<string | null>(null);

  useEffect(() => {
    getJson<WikiGroup[]>(`/api/ng/wiki/tree?lang=${lang}`)
      .then(setGroups).catch((e) => setError(String(e)));
  }, [lang]);

  const doSearch = async () => {
    if (!q.trim()) { setResults(null); return; }
    try {
      const r = await getJson<{ results: WikiDocMeta[] }>(
        `/api/ng/wiki/search?q=${encodeURIComponent(q)}&lang=${lang}`);
      setResults(r.results);
    } catch (e) { setError(String(e)); }
  };

  // 날짜로 문서 열기 — 사이드바 날짜 드롭 대신 여기서 분석할 날짜를 고른다
  const openByDate = async () => {
    setDateMsg(null);
    const docId = docType === "daily" ? `daily/${date}` : `weekly/${isoWeekOf(date)}`;
    try {
      await getJson(`/api/ng/wiki/doc/${docId}?lang=${lang}`);
      onNavigate(`/ng/doc/${docId}`);
    } catch {
      setDateMsg(tr(`해당 날짜의 문서가 없습니다: ${docId} (insight-worker 발행 후 조회 가능)`,
                    `No document for that date: ${docId} (available after insight-worker publishes)`));
    }
  };

  return (
    <div className="ng-page">
      <h1 className="ng-title">🧠 {tr("지식과 통찰", "Knowledge & Insights")}</h1>
      <p className="muted">
        {tr("AI가 매일 자동 발행하는 인사이트 위키 — 관리자는 신뢰 가능한 수치(SQL 사실)로 전체 상황을 파악하고, AI 컨설팅의 컨텍스트가 됩니다",
            "An insight wiki auto-published daily by AI — operators get trustworthy numbers (SQL facts) at a glance, and it becomes the context for AI consulting")}
      </p>

      <div className="ng-kpis">
        {[
          { type: "daily", icon: "📅", color: C.cons },
          { type: "weekly", icon: "📊", color: C.gen },
          { type: "event", icon: "🚨", color: C.gridImp },
        ].map((s) => {
          const g = groups.find((x) => x.type === s.type);
          return (
            <div key={s.type} className="ng-kpi ng-kpi-row">
              <div>
                <div className="ng-kpi-label">{docTypeLabel(lang, s.type, s.type)}</div>
                <div className="ng-kpi-value" style={{ color: s.color }}>{g?.count ?? 0}</div>
                <div className="ng-kpi-sub">
                  {g?.docs[0]?.period_start
                    ? `${tr("최신", "Latest")} ${String(g.docs[0].period_start).slice(0, 10)}`
                    : tr("발행 전", "Not yet published")}
                </div>
              </div>
              <div style={{ fontSize: 26 }}>{s.icon}</div>
            </div>
          );
        })}
        <div className="ng-kpi ng-kpi-row">
          <div>
            <div className="ng-kpi-label">{tr("지식 문서 합계", "Total knowledge docs")}</div>
            <div className="ng-kpi-value">{groups.reduce((a, g) => a + g.count, 0)}</div>
            <div className="ng-kpi-sub">{tr("한/영 동시 발행", "Published in KO & EN")}</div>
          </div>
          <div style={{ fontSize: 26 }}>🧠</div>
        </div>
      </div>

      <div className="ng-panel ng-form">
        <label>{tr("문서 유형", "Document type")}
          <select value={docType} onChange={(e) => setDocType(e.target.value as "daily" | "weekly")}>
            <option value="daily">{tr("일간 운영 브리프", "Daily Operations Brief")}</option>
            <option value="weekly">{tr("주간 성능 리포트", "Weekly Performance Report")}</option>
          </select>
        </label>
        <label>{tr("분석할 날짜", "Date to analyze")}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <button className="ng-btn primary" onClick={openByDate}>
          {tr("날짜로 조회", "Open by Date")}
        </button>
        <label style={{ flex: 1, minWidth: 200 }}>{tr("키워드 검색", "Keyword search")}
          <input value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch()}
            placeholder={tr("예: 자가소비율, MAPE, 배터리…", "e.g. self-consumption, MAPE, battery…")} />
        </label>
        <button className="ng-btn" onClick={doSearch}>{tr("검색", "Search")}</button>
      </div>

      {dateMsg && <div className="banner">{dateMsg}</div>}

      {error && <div className="banner error">{error}</div>}

      {results && (
        <div className="ng-panel">
          <div className="ng-panel-title">{tr("검색 결과", "Search results")} {results.length}{tr("건", "")}</div>
          {results.map((d) => (
            <button key={d.doc_id} className="ng-doc-link" onClick={() => onNavigate(`/ng/doc/${d.doc_id}`)}>
              <div className="ng-doc-link-title">{d.title}</div>
              <div className="ng-doc-link-meta">{d.doc_id}</div>
            </button>
          ))}
        </div>
      )}

      <div className="ng-cols">
        {groups.map((g) => (
          <div key={g.type} className="ng-panel">
            <div className="ng-panel-title">
              {docTypeLabel(lang, g.type, g.label)} <span className="tree-item-badge">{g.count}</span>
            </div>
            {g.docs.length === 0 && (
              <div className="muted">
                {tr("문서 없음 — insight-worker 가 데이터 축적 후 자동 발행합니다",
                    "No documents yet — insight-worker publishes automatically as data accumulates")}
              </div>
            )}
            {g.docs.slice(0, 8).map((d) => (
              <button key={d.doc_id} className="ng-doc-link" onClick={() => onNavigate(`/ng/doc/${d.doc_id}`)}>
                <div className="ng-doc-link-title">{d.title}</div>
                <div className="ng-doc-link-meta">{d.doc_id} · {d.llm_provider}</div>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ admin */

interface AdminStatus {
  llm_provider: string;
  llm_options: Record<string, unknown>;
  job: { running: boolean; task: string | null; started_at: string | null; finished_at: string | null; result: string | null; error: string | null };
  recent_docs: (WikiDocMeta & { llm_model?: string })[];
}

interface Device {
  id: number; side: string; device_type: string; name: string;
  capacity_kw: number; enabled: boolean; api_id: number | null; api_name: string | null;
}

interface DeviceData {
  groups: { side: string; devices: Device[] }[];
  totals: Record<string, number>;
}

interface ApiReg {
  id: number; name: string; kind: string; base_url: string; auth_type: string;
  api_key: string; enabled: boolean; last_check: string | null; last_status: string | null;
}

const SIDE_LABELS: Record<string, L2> = {
  supply: { ko: "에너지 공급", en: "Energy Supply" },
  storage: { ko: "에너지 저장", en: "Energy Storage" },
  demand: { ko: "에너지 수요", en: "Energy Demand" },
};

const DEVICE_TYPES: Record<string, { side: string; label: L2 }> = {
  pv: { side: "supply", label: { ko: "태양광(PV)", en: "Solar PV" } },
  wind: { side: "supply", label: { ko: "풍력", en: "Wind" } },
  fuel_cell: { side: "supply", label: { ko: "연료전지", en: "Fuel Cell" } },
  diesel: { side: "supply", label: { ko: "비상 발전기", en: "Backup Generator" } },
  ess: { side: "storage", label: { ko: "ESS 배터리", en: "ESS Battery" } },
  building_load: { side: "demand", label: { ko: "건물 부하", en: "Building Load" } },
  hvac: { side: "demand", label: { ko: "HVAC", en: "HVAC" } },
  ev_charging: { side: "demand", label: { ko: "EV 충전 부하", en: "EV Charging Load" } },
  machinery: { side: "demand", label: { ko: "설비 부하", en: "Machinery Load" } },
};

const API_KINDS: Record<string, L2> = {
  device: { ko: "기기 데이터", en: "Device data" },
  weather: { ko: "기상", en: "Weather" },
  market: { ko: "전력시장", en: "Power market" },
  other: { ko: "기타", en: "Other" },
};

export function NgAdmin({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { lang, tr } = useTr();
  const [st, setSt] = useState<AdminStatus | null>(null);
  const [task, setTask] = useState("all");
  const [force, setForce] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 기기 관리
  const [devices, setDevices] = useState<DeviceData | null>(null);
  const [devType, setDevType] = useState("pv");
  const [devName, setDevName] = useState("");
  const [devCap, setDevCap] = useState("10");
  const [devApi, setDevApi] = useState("");

  // API 등록
  const [apis, setApis] = useState<ApiReg[]>([]);
  const [apiName, setApiName] = useState("");
  const [apiKindV, setApiKindV] = useState("device");
  const [apiUrl, setApiUrl] = useState("");
  const [apiAuth, setApiAuth] = useState("none");
  const [apiKey, setApiKey] = useState("");

  const loadDevices = useCallback(() => {
    getJson<DeviceData>("/api/ng/admin/devices").then(setDevices).catch(() => {});
    getJson<ApiReg[]>("/api/ng/admin/apis").then(setApis).catch(() => {});
  }, []);

  const refresh = useCallback(() => {
    getJson<AdminStatus>(`/api/ng/admin/status?lang=${lang}`)
      .then(setSt).catch((e) => setError(String(e)));
  }, [lang]);

  useEffect(() => { loadDevices(); }, [loadDevices]);

  const addDevice = async () => {
    setError(null);
    try {
      await postJson("/api/ng/admin/devices", {
        side: DEVICE_TYPES[devType]?.side ?? "supply",
        device_type: devType,
        name: devName,
        capacity_kw: Number(devCap) || 0,
        api_id: devApi ? Number(devApi) : null,
      });
      setDevName("");
      loadDevices();
    } catch (e) { setError(String(e)); }
  };

  const toggleDevice = async (id: number) => {
    try { await postJson(`/api/ng/admin/devices/${id}/toggle`, {}); loadDevices(); }
    catch (e) { setError(String(e)); }
  };

  const deleteDevice = async (id: number) => {
    try {
      const res = await fetch(`/api/ng/admin/devices/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      loadDevices();
    } catch (e) { setError(String(e)); }
  };

  const addApi = async () => {
    setError(null);
    try {
      await postJson("/api/ng/admin/apis", {
        name: apiName, kind: apiKindV, base_url: apiUrl,
        auth_type: apiAuth, api_key: apiKey,
      });
      setApiName(""); setApiUrl(""); setApiKey("");
      loadDevices();
    } catch (e) { setError(String(e)); }
  };

  const testApi = async (id: number) => {
    setError(null);
    try {
      const r = await postJson<{ ok: boolean; status: string }>(`/api/ng/admin/apis/${id}/test`, {});
      setMsg(`${tr("API 연결 테스트", "API connection test")} #${id}: ${r.status}`);
      loadDevices();
    } catch (e) { setError(String(e)); }
  };

  const deleteApi = async (id: number) => {
    try {
      const res = await fetch(`/api/ng/admin/apis/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      loadDevices();
    } catch (e) { setError(String(e)); }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const regenerate = async () => {
    setMsg(null); setError(null);
    try {
      await postJson("/api/ng/admin/regenerate", { task, force, backfill_days: 7 });
      setMsg(tr("재생성 작업을 시작했습니다 — 상태가 아래에 갱신됩니다.",
                "Regeneration started — status updates below."));
      refresh();
    } catch (e) { setError(String(e)); }
  };

  const publish = async () => {
    setMsg(null); setError(null);
    try {
      const r = await postJson<{ published: number; model: string }>(
        "/api/ng/admin/publish_forecast", { target: "consumption_kw" });
      setMsg(`${tr("day-ahead 예측 발행 완료", "Day-ahead forecast published")} — ${r.model} · ${r.published} ${tr("포인트", "points")}`);
    } catch (e) { setError(String(e)); }
  };

  return (
    <div className="ng-page">
      <h1 className="ng-title">⚙ {tr("Wiki 관리자", "Wiki Admin")}</h1>
      <p className="muted">
        {tr("인사이트 발행·재생성, 예측 발행, LLM 공급자 상태를 관리합니다",
            "Manage insight publishing/regeneration, forecast publishing, and the LLM provider")}
      </p>

      <div className="ng-cols">
        <div className="ng-panel">
          <div className="ng-panel-title">{tr("LLM 공급자", "LLM Provider")}</div>
          <table className="ng-table">
            <tbody>
              <tr><td>provider</td><td><b>{st?.llm_provider ?? "—"}</b>{st?.llm_provider === "template" && <span className="muted"> {tr("(사실만, LLM 미사용)", "(facts only, no LLM)")}</span>}</td></tr>
              {Object.entries(st?.llm_options ?? {}).map(([k, v]) => (
                <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            {tr("전환: config.yaml `llm.provider` 또는 env `NGWIKI_LLM_PROVIDER` (claude | ollama | template)",
                "Switch via config.yaml `llm.provider` or env `NGWIKI_LLM_PROVIDER` (claude | ollama | template)")}
          </p>
        </div>

        <div className="ng-panel">
          <div className="ng-panel-title">{tr("인사이트 재생성", "Regenerate Insights")}</div>
          <div className="ng-form">
            <label>{tr("대상", "Scope")}
              <select value={task} onChange={(e) => setTask(e.target.value)}>
                <option value="all">{tr("전체", "All")}</option>
                <option value="daily">{tr("일간 브리프", "Daily briefs")}</option>
                <option value="weekly">{tr("주간 리포트", "Weekly reports")}</option>
                <option value="events">{tr("이벤트 노트", "Event notes")}</option>
              </select>
            </label>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
              {tr("강제 재생성(facts 동일해도)", "Force (even if facts unchanged)")}
            </label>
            <button className="ng-btn primary" onClick={regenerate} disabled={st?.job.running}>
              {st?.job.running ? tr("실행 중…", "Running…") : tr("재생성 실행", "Run Regeneration")}
            </button>
            <button className="ng-btn" onClick={publish}>
              {tr("내일 예측 발행(최적 모델)", "Publish Tomorrow's Forecast (best model)")}
            </button>
          </div>
          <table className="ng-table" style={{ marginTop: 8 }}>
            <tbody>
              <tr><td>{tr("작업 상태", "Job status")}</td><td>{st?.job.running ? `${tr("실행 중", "Running")} (${st.job.task})` : st?.job.result ?? tr("대기", "Idle")}</td></tr>
              <tr><td>{tr("시작", "Started")}</td><td className="muted">{dateTimeOf(st?.job.started_at, lang)}</td></tr>
              <tr><td>{tr("종료", "Finished")}</td><td className="muted">{dateTimeOf(st?.job.finished_at, lang)}</td></tr>
              {st?.job.error && <tr><td>{tr("오류", "Error")}</td><td className="muted">{st.job.error}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {msg && <div className="banner">{msg}</div>}
      {error && <div className="banner error">{error}</div>}

      {/* ------------------------------- 기기 관리 (공급/저장/수요) ------- */}
      <div className="ng-panel">
        <div className="ng-panel-title">
          🔌 {tr("기기 관리 — 에너지 공급 · 저장 · 수요", "Device Management — Energy Supply · Storage · Demand")}
        </div>
        <div className="ng-form" style={{ marginBottom: 12 }}>
          <label>{tr("기기 유형", "Device type")}
            <select value={devType} onChange={(e) => setDevType(e.target.value)}>
              {Object.entries(DEVICE_TYPES).map(([k, v]) => (
                <option key={k} value={k}>
                  {pick(lang, SIDE_LABELS[v.side])} · {pick(lang, v.label)}
                </option>
              ))}
            </select>
          </label>
          <label style={{ minWidth: 180 }}>{tr("기기 이름", "Device name")}
            <input value={devName} onChange={(e) => setDevName(e.target.value)}
              placeholder={tr("예: PV 어레이 B", "e.g. PV Array B")} />
          </label>
          <label style={{ width: 110 }}>{tr("용량(kW)", "Capacity (kW)")}
            <input value={devCap} onChange={(e) => setDevCap(e.target.value)} />
          </label>
          <label>{tr("연결 API", "Linked API")}
            <select value={devApi} onChange={(e) => setDevApi(e.target.value)}>
              <option value="">{tr("(없음 — 시뮬레이터)", "(none — simulator)")}</option>
              {apis.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </label>
          <button className="ng-btn primary" onClick={addDevice} disabled={!devName}>
            {tr("기기 추가", "Add Device")}
          </button>
        </div>

        {/* 용량 인포그래픽 — 공급/저장/수요 가용 용량 비교 */}
        {devices && (() => {
          const maxCap = Math.max(1, ...Object.values(devices.totals));
          const sideColor: Record<string, string> = { supply: C.gen, storage: C.batt, demand: C.cons };
          return (
            <div style={{ margin: "4px 0 14px" }}>
              {Object.entries(devices.totals).map(([side, cap]) => (
                <div key={side} className="ng-cat-bar">
                  <span className="ng-cat-bar-label">
                    {SIDE_LABELS[side] ? pick(lang, SIDE_LABELS[side]) : side}
                  </span>
                  <div className="ng-cat-bar-track">
                    <div className="ng-cat-bar-fill"
                      style={{ width: `${(cap / maxCap) * 100}%`, background: sideColor[side] ?? C.muted }} />
                  </div>
                  <span className="ng-cat-bar-value">{cap} kW</span>
                </div>
              ))}
            </div>
          );
        })()}

        <div className="ng-cols">
          {(devices?.groups ?? []).map((g) => (
            <div key={g.side} className="ng-panel" style={{ margin: 0 }}>
              <div className="ng-panel-title">
                {SIDE_LABELS[g.side] ? pick(lang, SIDE_LABELS[g.side]) : g.side}
                <span className="muted" style={{ fontWeight: 400 }}>
                  {" "}· {tr("가용 용량", "Available")} {devices?.totals[g.side] ?? 0} kW
                </span>
              </div>
              {g.devices.length === 0 && <div className="muted">{tr("등록된 기기 없음", "No devices")}</div>}
              {g.devices.map((d) => (
                <div key={d.id} className={`ng-gov-item ${d.enabled ? "" : "na"}`}>
                  <div style={{ flex: 1 }}>
                    <div className="ng-gov-title">
                      {d.name}
                      <span className="muted" style={{ fontWeight: 400 }}> · {fmt(d.capacity_kw, " kW", 0)}</span>
                    </div>
                    <div className="ng-kpi-sub">
                      {DEVICE_TYPES[d.device_type] ? pick(lang, DEVICE_TYPES[d.device_type].label) : d.device_type}
                      {d.api_name
                        ? ` · API: ${d.api_name}`
                        : ` · ${tr("시뮬레이터", "simulator")}`}
                    </div>
                  </div>
                  <button className="ng-btn" onClick={() => toggleDevice(d.id)}>
                    {d.enabled ? tr("사용 중", "Enabled") : tr("중지됨", "Disabled")}
                  </button>
                  <button className="ng-btn" onClick={() => deleteDevice(d.id)}>✕</button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ------------------------------- API 등록 ------------------------ */}
      <div className="ng-panel">
        <div className="ng-panel-title">🔗 {tr("API 등록 — 데이터 소스 연결", "API Registration — Data Source Connections")}</div>
        <div className="ng-form" style={{ marginBottom: 12 }}>
          <label style={{ minWidth: 160 }}>{tr("이름", "Name")}
            <input value={apiName} onChange={(e) => setApiName(e.target.value)}
              placeholder={tr("예: 기상청 단기예보", "e.g. KMA short-term forecast")} />
          </label>
          <label>{tr("종류", "Kind")}
            <select value={apiKindV} onChange={(e) => setApiKindV(e.target.value)}>
              {Object.entries(API_KINDS).map(([k, v]) => (
                <option key={k} value={k}>{pick(lang, v)}</option>
              ))}
            </select>
          </label>
          <label style={{ minWidth: 220 }}>Base URL
            <input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)}
              placeholder="https://api.example.com/v1" />
          </label>
          <label>{tr("인증", "Auth")}
            <select value={apiAuth} onChange={(e) => setApiAuth(e.target.value)}>
              <option value="none">{tr("없음", "None")}</option>
              <option value="api_key">API Key</option>
              <option value="bearer">Bearer Token</option>
            </select>
          </label>
          {apiAuth !== "none" && (
            <label style={{ minWidth: 160 }}>{tr("키/토큰", "Key/Token")}
              <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            </label>
          )}
          <button className="ng-btn primary" onClick={addApi} disabled={!apiName || !apiUrl}>
            {tr("API 등록", "Register API")}
          </button>
        </div>

        {apis.length === 0 && <div className="muted">{tr("등록된 API 가 없습니다.", "No APIs registered.")}</div>}
        {apis.length > 0 && (
          <table className="ng-table">
            <thead><tr>
              <th>{tr("이름", "Name")}</th><th>{tr("종류", "Kind")}</th><th>URL</th>
              <th>{tr("인증", "Auth")}</th><th>{tr("최근 점검", "Last check")}</th><th></th>
            </tr></thead>
            <tbody>
              {apis.map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td>{API_KINDS[a.kind] ? pick(lang, API_KINDS[a.kind]) : a.kind}</td>
                  <td className="muted">{a.base_url}</td>
                  <td>{a.auth_type}{a.api_key ? ` (${a.api_key})` : ""}</td>
                  <td className="muted">
                    {a.last_status ?? "—"}
                    {a.last_check ? ` · ${dateTimeOf(a.last_check, lang)}` : ""}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="ng-btn" onClick={() => testApi(a.id)}>{tr("연결 테스트", "Test")}</button>{" "}
                    <button className="ng-btn" onClick={() => deleteApi(a.id)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="ng-panel">
        <div className="ng-panel-title">{tr("최근 발행 문서", "Recently Published Documents")}</div>
        {(st?.recent_docs ?? []).map((d) => (
          <button key={d.doc_id} className="ng-doc-link" onClick={() => onNavigate(`/ng/doc/${d.doc_id}`)}>
            <div className="ng-doc-link-title">{d.title}</div>
            <div className="ng-doc-link-meta">{d.doc_id} · {d.llm_provider} · {dateTimeOf(d.updated_at, lang)}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- AI-Gov */

interface GovDoc {
  id: number; title: string; uploaded_at: string; analyzed_at: string | null;
  analyzer: string; chars: number; items: number; done: number;
}

interface GovItem {
  id: number; category: string; item: string; detail: string | null;
  source_quote: string | null; status: "todo" | "done" | "na";
}

interface GovChecklist {
  doc_id: number; total: number; done: number;
  groups: { category: string; items: GovItem[] }[];
}

const GOV_CATEGORY_LABELS: Record<string, L2> = {
  "개인정보": { ko: "개인정보", en: "Personal Data" },
  "보안": { ko: "보안", en: "Security" },
  "보고·기록": { ko: "보고·기록", en: "Reporting & Records" },
  "안전": { ko: "안전", en: "Safety" },
  "기타": { ko: "기타", en: "Other" },
};

export function NgGov() {
  const { lang, tr } = useTr();
  const [docs, setDocs] = useState<GovDoc[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [checklist, setChecklist] = useState<GovChecklist | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const loadDocs = useCallback(() => {
    getJson<GovDoc[]>("/api/ng/gov/documents").then(setDocs).catch((e) => setError(String(e)));
  }, []);

  const loadChecklist = useCallback((docId: number) => {
    setSelected(docId);
    getJson<GovChecklist>(`/api/ng/gov/checklist?doc_id=${docId}`)
      .then(setChecklist).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  const onFile = (f: File | null) => {
    if (!f) return;
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
    f.text().then(setContent);
  };

  const upload = async () => {
    setBusy(true); setError(null); setMsg(null);
    try {
      const r = await postJson<{ id: number }>("/api/ng/gov/documents", { title, content });
      setMsg(tr("업로드 완료 — 이제 [분석 실행]으로 체크리스트를 생성하세요.",
                "Uploaded — now click [Analyze] to generate the checklist."));
      setTitle(""); setContent("");
      loadDocs(); loadChecklist(r.id);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };

  const analyze = async (docId: number) => {
    setBusy(true); setError(null); setMsg(null);
    try {
      const r = await postJson<{ items: number; analyzer: string }>(`/api/ng/gov/documents/${docId}/analyze`, {});
      setMsg(`${tr("분석 완료", "Analysis complete")} (${r.analyzer}) — ${r.items} ${tr("건의 체크리스트 생성", "checklist items generated")}`);
      loadDocs(); loadChecklist(docId);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };

  const setStatus = async (item: GovItem, status: GovItem["status"]) => {
    try {
      await postJson(`/api/ng/gov/checklist/${item.id}/status`, { status });
      if (selected) loadChecklist(selected);
      loadDocs();
    } catch (e) { setError(String(e)); }
  };

  return (
    <div className="ng-page">
      <h1 className="ng-title">📜 {tr("AI-Gov — 법률 분석·준수 체크리스트", "AI-Gov — Law Analysis & Compliance Checklist")}</h1>
      <p className="muted">
        {tr("관계 법률·규정을 업로드하면 AI가 의무·금지 조항을 추출해 체크리스트로 만듭니다. 모든 항목은 원문 인용(근거)을 보존합니다 — 고객 정보 관리 등 운영 업무의 AI-Gov 판정 기준이 됩니다.",
            "Upload applicable laws and regulations; the AI extracts obligations and prohibitions into a checklist. Every item preserves a source quote — the AI-Gov baseline for operations such as customer data management.")}
      </p>

      <div className="ng-panel">
        <div className="ng-panel-title">① {tr("법률·규정 업로드", "Upload Law / Regulation")}</div>
        <div className="ng-form">
          <label style={{ minWidth: 260 }}>{tr("문서 제목", "Document title")}
            <input value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder={tr("예: 개인정보 보호법 제29조~", "e.g. PIPA Articles 29–")} />
          </label>
          <label>{tr("파일(.txt/.md)", "File (.txt/.md)")}
            <input type="file" accept=".txt,.md,.text" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
          </label>
        </div>
        <textarea
          className="ng-textarea"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={tr("법률/규정 원문을 붙여넣거나 파일을 선택하세요 (조문 단위로 분석됩니다)",
                          "Paste the law/regulation text or choose a file (analyzed clause by clause)")}
          rows={6}
        />
        <button className="ng-btn primary" onClick={upload} disabled={busy || !title || content.length < 20}>
          {busy ? tr("처리 중…", "Working…") : tr("업로드", "Upload")}
        </button>
      </div>

      {msg && <div className="banner">{msg}</div>}
      {error && <div className="banner error">{error}</div>}

      <div className="ng-panel">
        <div className="ng-panel-title">② {tr("업로드된 문서", "Uploaded Documents")}</div>
        {docs.length === 0 && <div className="muted">{tr("업로드된 법률 문서가 없습니다.", "No law documents uploaded yet.")}</div>}
        {docs.length > 0 && (
          <table className="ng-table">
            <thead><tr><th>{tr("제목", "Title")}</th><th>{tr("분량", "Size")}</th><th>{tr("분석", "Analysis")}</th><th>{tr("체크리스트", "Checklist")}</th><th></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className={selected === d.id ? "best" : ""}>
                  <td><button className="ng-link" onClick={() => loadChecklist(d.id)}>{d.title}</button></td>
                  <td className="muted">{d.chars.toLocaleString()}{tr("자", " chars")}</td>
                  <td>{d.analyzed_at ? `${tr("완료", "Done")} (${d.analyzer})` : tr("미분석", "Not analyzed")}</td>
                  <td>{d.items > 0 ? `${d.done}/${d.items} ${tr("이행", "done")}` : "—"}</td>
                  <td><button className="ng-btn" onClick={() => analyze(d.id)} disabled={busy}>{tr("분석 실행", "Analyze")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {checklist && (
        <div className="ng-panel">
          <div className="ng-panel-title">
            ③ {tr("준수 체크리스트", "Compliance Checklist")}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 18, margin: "6px 0 14px" }}>
            <Donut
              value={checklist.total ? (checklist.done / checklist.total) * 100 : 0}
              size={92} stroke={11}
              color={checklist.done === checklist.total && checklist.total > 0 ? C.ok : C.cons}
              text={`${checklist.done}/${checklist.total}`}
              sub={tr("이행률", "Compliance")}
            />
            <div style={{ flex: 1 }}>
              {checklist.groups.map((g) => {
                const done = g.items.filter((i) => i.status === "done").length;
                const pct = g.items.length ? (done / g.items.length) * 100 : 0;
                return (
                  <div key={g.category} className="ng-cat-bar">
                    <span className="ng-cat-bar-label">
                      {GOV_CATEGORY_LABELS[g.category] ? pick(lang, GOV_CATEGORY_LABELS[g.category]) : g.category}
                    </span>
                    <div className="ng-cat-bar-track">
                      <div className="ng-cat-bar-fill" style={{ width: `${pct}%`, background: C.cons }} />
                    </div>
                    <span className="ng-cat-bar-value">{done}/{g.items.length}</span>
                  </div>
                );
              })}
            </div>
          </div>
          {checklist.groups.map((g) => (
            <div key={g.category} className="ng-gov-group">
              <div className="ng-gov-cat">
                {GOV_CATEGORY_LABELS[g.category] ? pick(lang, GOV_CATEGORY_LABELS[g.category]) : g.category}
              </div>
              {g.items.map((it) => (
                <div key={it.id} className={`ng-gov-item ${it.status}`}>
                  <input
                    type="checkbox"
                    checked={it.status === "done"}
                    onChange={(e) => setStatus(it, e.target.checked ? "done" : "todo")}
                  />
                  <div style={{ flex: 1 }}>
                    <div className="ng-gov-title">{it.item}</div>
                    {it.detail && <div className="ng-kpi-sub">{it.detail}</div>}
                    {it.source_quote && (
                      <div className="ng-gov-quote">{tr("근거", "Source")}: “{it.source_quote}”</div>
                    )}
                  </div>
                  <select value={it.status} onChange={(e) => setStatus(it, e.target.value as GovItem["status"])}>
                    <option value="todo">{tr("미이행", "To do")}</option>
                    <option value="done">{tr("이행", "Done")}</option>
                    <option value="na">{tr("해당없음", "N/A")}</option>
                  </select>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- docs */

interface WikiDoc {
  doc_id: string; title: string; content_md: string;
  llm_provider: string; llm_model: string; updated_at: string;
}

export function NgDocView({ id, onNavigate }: { id: string; onNavigate: (p: string) => void }) {
  const { lang, tr } = useTr();
  const [doc, setDoc] = useState<WikiDoc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDoc(null);
    getJson<WikiDoc>(`/api/ng/wiki/doc/${id}?lang=${lang}`)
      .then(setDoc).catch((e) => setError(String(e)));
  }, [id, lang]);

  if (error) return <div className="banner error">{error}</div>;
  if (!doc) return <div className="muted pad">{tr("문서를 불러오는 중…", "Loading document…")}</div>;

  return (
    <div className="ng-page">
      <div className="ng-doc-meta">
        {doc.doc_id} · {tr("생성", "Generated by")}: {doc.llm_provider}
        {doc.llm_model ? ` (${doc.llm_model})` : ""} · {tr("갱신", "Updated")}{" "}
        {dateTimeOf(doc.updated_at, lang)}
      </div>
      <Markdown source={doc.content_md} onNavigate={onNavigate} />
    </div>
  );
}
