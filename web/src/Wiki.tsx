import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type WikiAcl,
  type WikiHit,
  type WikiPageDetail,
  type WikiPageSummary,
  type WikiStats,
  type WikiTypeInfo,
} from "./api";
import Markdown, { headingId } from "./Markdown";
import WikiTree from "./WikiTree";
import { useLang, type StringKey } from "./i18n";

export type WikiTab = "browse" | "search" | "catalog";

export const WIKI_TABS: WikiTab[] = ["browse", "search", "catalog"];

const TAB_KEY: Record<WikiTab, StringKey> = {
  browse: "wikiTabBrowse",
  search: "wikiTabSearch",
  catalog: "wikiTabCatalog",
};

const STATUS_KEY: Record<string, StringKey> = {
  draft: "wikiStatusDraft",
  reviewed: "wikiStatusReviewed",
  deprecated: "wikiStatusDeprecated",
};

/** `[[id]]` 를 클릭 가능한 링크로. 위키 링크가 글자로만 남으면 그래프가 죽은 문서가 된다. */
const WIKI_LINK = /\[\[([^\[\]|]+?)(?:\|([^\[\]]*))?\]\]/g;
const LINK_PREFIX = "/wiki/p/";

function linkify(body: string): string {
  return body.replace(WIKI_LINK, (_m, id: string, label?: string) =>
    `[${label?.trim() || id.trim()}](${LINK_PREFIX}${id.trim()})`
  );
}

const STATUS_CLASS: Record<string, string> = {
  draft: "s-pending",
  reviewed: "s-ok",
  deprecated: "s-rejected",
};

/** 등급은 화면에서 고르지만 판정은 서버가 한다 — 여기 값은 질의 인자일 뿐이다. */
const ACLS: WikiAcl[] = ["public", "internal", "confidential", "restricted"];

/** 열람 등급은 사람마다 다르다. 탭을 옮길 때마다 다시 고르게 하지 않는다. */
const ACL_KEY = "llmwiki.wiki.acl";

function readAcl(): WikiAcl {
  try {
    const v = localStorage.getItem(ACL_KEY);
    return (ACLS as string[]).includes(v ?? "") ? (v as WikiAcl) : "internal";
  } catch {
    return "internal";
  }
}

export default function Wiki({
  tab,
  onTab,
}: {
  tab: WikiTab;
  onTab: (t: WikiTab) => void;
}) {
  const { t } = useLang();
  const [acl, setAclState] = useState<WikiAcl>(readAcl);
  const [err, setErr] = useState<string | null>(null);
  // 선택한 페이지를 탭보다 위에 둔다 — 검색 결과를 눌렀을 때 열람 탭에서 그 페이지가
  // 열려야 한다. 탭 안에 가둬 두면 찾고도 못 여는 화면이 된다.
  const [selected, setSelected] = useState<string | null>(null);

  const setAcl = useCallback((next: WikiAcl) => {
    setAclState(next);
    try {
      localStorage.setItem(ACL_KEY, next);
    } catch {
      /* 프라이빗 모드에서 실패해도 세션 안에서는 동작한다 */
    }
  }, []);

  return (
    <div className="page wiki">
      <h1>{t("wikiTitle")}</h1>
      <p className="lede">{t("wikiLede")}</p>

      <div className="wiki-acl">
        <label>
          <span>{t("wikiAclLabel")}</span>
          <select value={acl} onChange={(e) => setAcl(e.target.value as WikiAcl)}>
            {ACLS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <span className="muted small">{t("wikiAclNote")}</span>
      </div>

      {err && <div className="banner error">{err}</div>}

      <div className="tabs">
        {WIKI_TABS.map((key) => (
          <button
            key={key}
            className={`tab ${tab === key ? "active" : ""}`}
            onClick={() => onTab(key)}
          >
            {t(TAB_KEY[key])}
          </button>
        ))}
      </div>

      {tab === "browse" && (
        <BrowseTab acl={acl} selected={selected} onSelect={setSelected} onError={setErr} />
      )}
      {tab === "search" && (
        <SearchTab
          acl={acl}
          onError={setErr}
          onOpen={(id) => {
            setSelected(id);
            onTab("browse");
          }}
        />
      )}
      {tab === "catalog" && <CatalogTab onError={setErr} />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 열람
// --------------------------------------------------------------------------- //
function BrowseTab({
  acl,
  selected,
  onSelect,
  onError,
}: {
  acl: WikiAcl;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onError: (m: string | null) => void;
}) {
  const { t } = useLang();
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [types, setTypes] = useState<WikiTypeInfo[]>([]);
  const [stats, setStats] = useState<WikiStats | null>(null);
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState<WikiPageDetail | null>(null);

  useEffect(() => {
    api.wiki
      .pages(acl, type || undefined, status || undefined)
      .then((r) => {
        setPages(r.pages);
        setTypes(r.types);
        setStats(r.stats);
        onError(null);
      })
      .catch((e) => onError(e.message));
  }, [acl, type, status, onError]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    api.wiki
      .page(selected, acl)
      .then((r) => {
        setDetail(r);
        onError(null);
      })
      .catch((e) => {
        setDetail(null);
        onError(e.message);
      });
  }, [selected, acl, onError]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return pages;
    return pages.filter(
      (p) =>
        p.title.toLowerCase().includes(q) ||
        p.stable_id.toLowerCase().includes(q) ||
        p.tags.some((tag) => tag.toLowerCase().includes(q))
    );
  }, [pages, filter]);


  return (
    <div className="wiki-browse">
      <aside className="wiki-list">
        <div className="wiki-filters">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("wikiSearchPlaceholder")}
          />
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">{t("wikiTypeAll")}</option>
            {types.map((ti) => (
              <option key={ti.name} value={ti.name}>
                {ti.ko}
              </option>
            ))}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("wikiStatusAll")}</option>
            {Object.keys(STATUS_KEY).map((s) => (
              <option key={s} value={s}>
                {t(STATUS_KEY[s])}
              </option>
            ))}
          </select>
        </div>

        {stats && (
          <p className="muted small">
            {t("adminStorePages", {
              pages: shown.length,
              verified: shown.filter((p) => p.numeric_verified).length,
            })}
            {shown.length < stats.pages && (
              <> · {t("wikiAclHidden", { n: stats.pages - shown.length })}</>
            )}
          </p>
        )}

        {shown.length === 0 ? (
          <div className="empty">
            <p className="empty-title">{t("wikiNoPages")}</p>
            <p className="muted">{t("wikiNoPagesHint")}</p>
          </div>
        ) : (
          <WikiTree
            pages={shown}
            types={types}
            selected={selected}
            onPick={onSelect}
          />
        )}
      </aside>

      <div className="wiki-detail">
        {detail ? (
          <PageView detail={detail} types={types} onPick={onSelect} />
        ) : (
          <div className="muted pad">{t("wikiPickPage")}</div>
        )}
      </div>
    </div>
  );
}

function PageView({
  detail,
  types,
  onPick,
}: {
  detail: WikiPageDetail;
  types: WikiTypeInfo[];
  onPick: (id: string) => void;
}) {
  const { t } = useLang();
  const [raw, setRaw] = useState(false);
  const p = detail.page;
  const typeLabel = types.find((ti) => ti.name === p.type)?.ko ?? p.type;
  // 이 페이지 안의 절 목록. 개선안 카드는 절이 예닐곱이라 스크롤로만 찾기 어렵다.
  const sections = Array.from(p.body.matchAll(/^##\s+(.+)$/gm)).map((m) => m[1].trim());
  // 상위는 역링크 중 '나를 품는' 것들이다 — 진단 건과 사업장이 여기 걸린다.
  const parents = detail.backlinks.filter((b) =>
    ["diagnosis", "facility"].includes(b.type)
  );

  return (
    <article className="wiki-page">
      <header>
        {/* 이 페이지가 무엇의 일부인지 — 계층은 목록에만 있으면 안 된다.
            페이지를 열고 나면 목록은 시야에서 밀린다. */}
        <nav className="crumbs">
          <span className="crumb-type">{typeLabel}</span>
          {parents.map((b) => (
            <button key={b.stable_id} className="crumb" onClick={() => onPick(b.stable_id)}>
              {b.title}
            </button>
          ))}
        </nav>
        <h2>{p.title}</h2>
        {/* 색이 판정을 대신하지 않도록 라벨을 함께 쓴다. 그리고 판정과 무관한 값
            (버전·ID·측정근거)은 칩에서 빼 아래 한 줄로 내린다 — 칩이 여섯 개면
            무엇이 중요한지가 사라진다. */}
        <div className="wiki-badges">
          <span className={`chip ${STATUS_CLASS[p.status] ?? ""}`}>
            {t(STATUS_KEY[p.status] ?? "wikiStatusDraft")}
          </span>
          <span className={`chip ${p.numeric_verified ? "s-ok" : "s-blocked"}`}>
            {p.numeric_verified ? t("wikiVerified") : t("wikiUnverified")}
          </span>
          <span className="chip acl">{p.acl}</span>
        </div>
        <p className="wiki-meta">
          <code className="inline-code">{p.stable_id}</code>
          <span>v{p.version}</span>
          <span>{p.measurement_basis}</span>
          {p.owner && <span>{p.owner}</span>}
        </p>
      </header>

      {!p.numeric_verified && (
        <div className="banner warn">{t("wikiUnverifiedNote")}</div>
      )}

      <section className="wiki-source">
        <h3>{t("wikiSource")}</h3>
        <ul>
          {p.source_span.map((s, i) => (
            <li key={i}>
              <code className="inline-code">{s.doc}</code>
              {s.pages.length > 0 && <> · p.{s.pages.join(", ")}</>}
              {s.section && <> · {s.section}</>}
            </li>
          ))}
        </ul>
      </section>

      {sections.length > 2 && !raw && (
        <nav className="page-toc">
          {sections.map((h) => (
            <a
              key={h}
              href={`#${headingId(h)}`}
              onClick={(e) => {
                // 스크롤되는 것은 문서가 아니라 `.content` 다. 해시 이동에 맡기면
                // 주소만 바뀌고 화면은 그대로 있는다.
                e.preventDefault();
                // behavior:"smooth" 를 주면 애니메이션을 무시하는 환경(감속 모션
                // 설정 등)에서 **아무 일도 일어나지 않는다.** 이동은 확실하게 하고,
                // 부드럽게 할지는 CSS(`scroll-behavior`)가 정하게 둔다.
                document
                  .getElementById(headingId(h))
                  ?.scrollIntoView({ block: "start" });
              }}
            >
              {h}
            </a>
          ))}
        </nav>
      )}

      <div className="wiki-body">
        {raw ? (
          <pre className="wiki-raw">{p.raw}</pre>
        ) : (
          <Markdown
            anchors
            source={linkify(p.body)}
            onNavigate={(path) =>
              path.startsWith(LINK_PREFIX) && onPick(path.slice(LINK_PREFIX.length))
            }
          />
        )}
      </div>

      <button className="tables-link" onClick={() => setRaw((v) => !v)}>
        {raw ? t("wikiFrontMatter") : t("wikiRaw")}
      </button>

      {p.related.length > 0 && (
        <section>
          <h3>{t("wikiRelated")}</h3>
          <div className="wiki-links">
            {p.related.map((id) => (
              <button key={id} className="chip link" onClick={() => onPick(id)}>
                {id}
              </button>
            ))}
          </div>
        </section>
      )}

      {detail.backlinks.length > 0 && (
        <section>
          <h3>{t("wikiBacklinks")}</h3>
          <p className="muted small">{t("wikiBacklinkNote")}</p>
          <div className="wiki-links">
            {detail.backlinks.map((b) => (
              <button
                key={b.stable_id}
                className="chip link"
                onClick={() => onPick(b.stable_id)}
              >
                {b.title}
              </button>
            ))}
          </div>
        </section>
      )}

      {detail.findings.length > 0 && (
        <section>
          <h3>{t("wikiFindings")}</h3>
          <ul className="finding-list">
            {detail.findings.map((f, i) => (
              <li key={i} className={`sev-${f.severity}`}>
                <code className="inline-code">{f.code}</code> {f.message}
                {f.hint && <div className="muted small">{f.hint}</div>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {detail.review.length > 0 && (
        <section>
          <h3>{t("wikiReviewHistory")}</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>{t("adminColAt")}</th>
                <th>{t("adminColDecision")}</th>
                <th>{t("adminColActor")}</th>
                <th>{t("adminNote")}</th>
              </tr>
            </thead>
            <tbody>
              {detail.review.map((r, i) => (
                <tr key={i}>
                  <td>{r.at}</td>
                  <td>{r.decision}</td>
                  <td>{r.actor}</td>
                  <td>{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </article>
  );
}

// --------------------------------------------------------------------------- //
// 검색
// --------------------------------------------------------------------------- //
function SearchTab({
  acl,
  onError,
  onOpen,
}: {
  acl: WikiAcl;
  onError: (m: string | null) => void;
  onOpen: (id: string) => void;
}) {
  const { t } = useLang();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<WikiHit[] | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits(null);
      return;
    }
    const timer = setTimeout(() => {
      api.wiki
        .search(q, acl)
        .then((r) => {
          setHits(r.results);
          onError(null);
        })
        .catch((e) => onError(e.message));
    }, 250);
    return () => clearTimeout(timer);
  }, [query, acl, onError]);

  return (
    <div className="wiki-search">
      <p className="muted small">{t("wikiSearchNote")}</p>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t("wikiSearchPlaceholder")}
      />
      {hits === null ? (
        <div className="muted pad">{t("wikiSearchIdle")}</div>
      ) : hits.length === 0 ? (
        <div className="muted pad">{t("wikiNoHits")}</div>
      ) : (
        <ul className="hit-list">
          {hits.map((h) => (
            <li key={h.stable_id}>
              <div className="hit-head">
                <button className="hit-title" onClick={() => onOpen(h.stable_id)}>
                  {h.title}
                </button>
                <span className="chip acl">{h.acl}</span>
                {!h.numeric_verified && (
                  <span className="chip s-blocked">{t("wikiUnverified")}</span>
                )}
                <span className="muted small">
                  {t("wikiChannels")}:{" "}
                  {Object.entries(h.ranks)
                    .map(([c, r]) => `${c} #${r}`)
                    .join(" · ") || "—"}
                </span>
              </div>
              <code className="inline-code">{h.stable_id}</code>
              <p className="muted small">{h.snippet}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 카탈로그
// --------------------------------------------------------------------------- //
function CatalogTab({ onError }: { onError: (m: string | null) => void }) {
  const { t } = useLang();
  const [text, setText] = useState("");

  useEffect(() => {
    fetch(api.wiki.catalogUrl())
      .then((r) => r.text())
      .then((body) => {
        setText(body);
        onError(null);
      })
      .catch((e) => onError(e.message));
  }, [onError]);

  return (
    <div className="wiki-catalog">
      <p className="muted small">{t("wikiCatalogNote")}</p>
      <Markdown source={text} onNavigate={() => {}} />
    </div>
  );
}
