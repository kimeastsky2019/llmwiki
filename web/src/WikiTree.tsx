import { useMemo, useState } from "react";
import type { WikiPageSummary, WikiTypeInfo } from "./api";
import { useLang, type StringKey } from "./i18n";

/** 위키 목록의 계층 — 타입별 평면 목록이 아니라 **지식의 구조**를 보여 준다.
 *
 * 26장을 타입 아홉 개로 나눠 늘어놓으면 어느 것이 어느 진단에 딸린 것인지 알 수 없다.
 * 이 도메인의 구조는 이렇다.
 *
 *   진단 건(dgn) ─ 허브
 *     ├ 사업장(fac)
 *     ├ 설비(eqp) · 지표(mtr)
 *     └ 원문(src)
 *   재사용 자산 ─ 사업장을 넘어 반복되는 것
 *     개선안(ecm) · 인사이트(cpt) · 법규·계수(reg)
 *
 * 개선안이 진단 아래 들어가지 않는 것이 핵심이다. 개선안은 사업장이 달라도 같은
 * 카드를 다시 쓰는 자산이라, 특정 진단에 매달아 두면 재사용이라는 목적이 흐려진다.
 */

/** 진단 아래에 매달리는 타입. 순서가 곧 화면의 순서다. */
const UNDER_DIAGNOSIS: string[] = ["facility", "equipment", "metric", "source", "vendor"];

/** 사업장을 넘는 재사용 자산. */
const SHARED: string[] = ["measure", "concept", "regulation"];

const BAND_KEY: Record<string, StringKey> = {
  diagnosis: "wikiBandDiagnosis",
  shared: "wikiBandShared",
  other: "wikiBandOther",
};

interface Group {
  type: string;
  pages: WikiPageSummary[];
}

export default function WikiTree({
  pages,
  types,
  selected,
  onPick,
}: {
  pages: WikiPageSummary[];
  types: WikiTypeInfo[];
  selected: string | null;
  onPick: (id: string) => void;
}) {
  const { t } = useLang();
  const label = (name: string) =>
    types.find((ti) => ti.name === name)?.ko ?? name;

  const bands = useMemo(() => build(pages), [pages]);
  if (pages.length === 0) return null;

  return (
    <div className="wiki-tree">
      {bands.diagnoses.map((d) => (
        <section key={d.page.stable_id} className="wt-band">
          <h3 className="wt-band-title">{t(BAND_KEY.diagnosis)}</h3>
          <button
            className={`wt-root ${selected === d.page.stable_id ? "active" : ""}`}
            onClick={() => onPick(d.page.stable_id)}
          >
            <span className="wt-root-title">{d.page.title}</span>
            <Flags page={d.page} />
          </button>
          {d.groups.map((g) => (
            <TypeGroup
              key={g.type}
              title={label(g.type)}
              group={g}
              selected={selected}
              onPick={onPick}
              // 지표는 열두 장까지 나온다. 다 펼치면 목록이 지표로 뒤덮여
              // 정작 개선안이 화면 밖으로 밀린다.
              collapsed={g.type === "metric" && g.pages.length > 4}
            />
          ))}
        </section>
      ))}

      {bands.shared.length > 0 && (
        <section className="wt-band">
          <h3 className="wt-band-title">
            {t(BAND_KEY.shared)}
            <span className="wt-band-note">{t("wikiBandSharedNote")}</span>
          </h3>
          {bands.shared.map((g) => (
            <TypeGroup
              key={g.type}
              title={label(g.type)}
              group={g}
              selected={selected}
              onPick={onPick}
            />
          ))}
        </section>
      )}

      {bands.other.length > 0 && (
        <section className="wt-band">
          <h3 className="wt-band-title">{t(BAND_KEY.other)}</h3>
          {bands.other.map((g) => (
            <TypeGroup
              key={g.type}
              title={label(g.type)}
              group={g}
              selected={selected}
              onPick={onPick}
            />
          ))}
        </section>
      )}
    </div>
  );
}

function TypeGroup({
  title,
  group,
  selected,
  onPick,
  collapsed = false,
}: {
  title: string;
  group: Group;
  selected: string | null;
  onPick: (id: string) => void;
  collapsed?: boolean;
}) {
  const [open, setOpen] = useState(!collapsed);
  const hasSelected = group.pages.some((p) => p.stable_id === selected);

  return (
    <div className={`wt-group ${open || hasSelected ? "open" : ""}`}>
      <button className="wt-group-head" onClick={() => setOpen((v) => !v)}>
        <span className="wt-caret">{open || hasSelected ? "▾" : "▸"}</span>
        <span className="wt-group-title">{title}</span>
        <span className="wt-count">{group.pages.length}</span>
      </button>
      {(open || hasSelected) && (
        <ul className="wt-items">
          {group.pages.map((p) => (
            <li key={p.stable_id}>
              <button
                className={`wt-item ${selected === p.stable_id ? "active" : ""}`}
                onClick={() => onPick(p.stable_id)}
              >
                <span className="wt-item-title">{p.title}</span>
                <Flags page={p} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 상태 표시는 **문제가 있을 때만** 낸다. 26장이 전부 배지를 달면 배지가 배경이 된다. */
function Flags({ page }: { page: WikiPageSummary }) {
  const { t } = useLang();
  return (
    <span className="wt-flags">
      {!page.numeric_verified && (
        <span className="wt-flag warn" title={t("wikiUnverified")}>
          !
        </span>
      )}
      {page.status === "draft" && (
        <span className="wt-flag draft" title={t("wikiStatusDraft")}>
          {t("wikiStatusDraft")}
        </span>
      )}
      {page.status === "deprecated" && (
        <span className="wt-flag gone" title={t("wikiStatusDeprecated")}>
          {t("wikiStatusDeprecated")}
        </span>
      )}
    </span>
  );
}

/** 페이지 목록 → 밴드 구조. 부모가 권한 밖이면 자식은 '그 밖' 으로 내려간다 —
 *  사라지게 두면 사용자는 지식이 없다고 결론 낸다. */
function build(pages: WikiPageSummary[]) {
  const byId = new Map(pages.map((p) => [p.stable_id, p]));
  const claimed = new Set<string>();

  const diagnoses = pages
    .filter((p) => p.type === "diagnosis")
    .map((page) => {
      claimed.add(page.stable_id);
      const children = page.related
        .map((id) => byId.get(id))
        .filter((p): p is WikiPageSummary => !!p && UNDER_DIAGNOSIS.includes(p.type));
      // 원문 페이지는 진단을 링크하지, 진단이 원문을 링크하지 않을 수 있다.
      for (const p of pages) {
        if (p.type === "source" && p.related.includes(page.stable_id) && !children.includes(p)) {
          children.push(p);
        }
      }
      children.forEach((c) => claimed.add(c.stable_id));
      return { page, groups: groupByType(children, UNDER_DIAGNOSIS) };
    });

  const shared = groupByType(
    pages.filter((p) => SHARED.includes(p.type)),
    SHARED
  );
  shared.forEach((g) => g.pages.forEach((p) => claimed.add(p.stable_id)));

  const rest = pages.filter((p) => !claimed.has(p.stable_id));
  const other = groupByType(rest, [...UNDER_DIAGNOSIS, "diagnosis"]);

  return { diagnoses, shared, other };
}

function groupByType(pages: WikiPageSummary[], order: string[]): Group[] {
  const map = new Map<string, WikiPageSummary[]>();
  for (const p of pages) {
    const list = map.get(p.type) ?? [];
    if (!list.some((x) => x.stable_id === p.stable_id)) list.push(p);
    map.set(p.type, list);
  }
  const known = order.filter((t) => map.has(t));
  const unknown = [...map.keys()].filter((t) => !order.includes(t)).sort();
  return [...known, ...unknown].map((type) => ({
    type,
    pages: (map.get(type) ?? []).sort((a, b) => a.title.localeCompare(b.title, "ko")),
  }));
}
