/** 솔루션 정의 — 한 제품 안에 목적이 다른 두 작업 공간이 있다.
 *
 * 두 솔루션은 **같은 엔진**(sLM·Grok·검색·규제 판정)을 쓰지만, 다루는 대상과
 * 사용자가 다르다. 한 사이드바에 여섯 개를 늘어놓으면 "테이블 목록" 옆에
 * "위키 관리자" 가 붙어, 처음 보는 사람은 이게 한 흐름인 줄 안다.
 *
 * 그래서 메뉴를 솔루션으로 가르고, 엔진은 메뉴가 아니라 **레이어**로 항상 바닥에
 * 깔아 둔다. 엔진이 메뉴가 되면 사용자는 그것을 기능으로 오해한다.
 */
import type { StringKey } from "./i18n";

export type SolutionCode = "code" | "report";

export interface SolutionMenu {
  /** 이동할 경로 */
  path: string;
  labelKey: StringKey;
  descKey: StringKey;
  /** 이 항목이 활성인지 판정할 경로 접두사 */
  match: string;
}

export interface Solution {
  code: SolutionCode;
  labelKey: StringKey;
  taglineKey: StringKey;
  /** 솔루션을 고르면 가는 곳 */
  home: string;
  menus: SolutionMenu[];
  /** 이 솔루션이 실제로 쓰는 엔진 (엔진 패널에서 어느 쪽이 쓰는지 표시) */
  engines: string[];
}

export const SOLUTIONS: Solution[] = [
  {
    code: "code",
    labelKey: "solCodeName",
    taglineKey: "solCodeTagline",
    home: "/",
    menus: [
      { path: "/", labelKey: "solCodeMenuPrograms", descKey: "solCodeMenuProgramsDesc", match: "/p/" },
      { path: "/tables", labelKey: "tablesLink", descKey: "solCodeMenuTablesDesc", match: "/tables" },
      { path: "/reg", labelKey: "regLink", descKey: "solCodeMenuRegDesc", match: "/reg" },
    ],
    engines: ["grok", "sllm", "aigov"],
  },
  {
    code: "report",
    labelKey: "solReportName",
    taglineKey: "solReportTagline",
    home: "/kb",
    menus: [
      { path: "/kb", labelKey: "kbLink", descKey: "solReportMenuKbDesc", match: "/kb" },
      { path: "/wiki", labelKey: "wikiLink", descKey: "solReportMenuWikiDesc", match: "/wiki" },
      { path: "/admin", labelKey: "adminLink", descKey: "solReportMenuAdminDesc", match: "/admin" },
      { path: "/checklist", labelKey: "checklistLink", descKey: "solReportMenuChecklistDesc", match: "/checklist" },
      { path: "/timeline", labelKey: "timelineLink", descKey: "solReportMenuTimelineDesc", match: "/timeline" },
    ],
    engines: ["sllm", "grok", "rag", "aigov"],
  },
];

/** 경로가 어느 솔루션에 속하는가. 솔루션을 별도 상태로 들지 않는 이유는,
 *  주소창으로 바로 들어온 사람과 메뉴로 들어온 사람이 다른 화면을 보면 안 되기 때문이다. */
export function solutionOf(path: string): SolutionCode {
  if (
    path.startsWith("/kb") ||
    path.startsWith("/wiki") ||
    path.startsWith("/admin") ||
    path.startsWith("/checklist") ||
    path.startsWith("/timeline")
  ) {
    return "report";
  }
  return "code";
}

export function solution(code: SolutionCode): Solution {
  return SOLUTIONS.find((s) => s.code === code) ?? SOLUTIONS[0];
}
