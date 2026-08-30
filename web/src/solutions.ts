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

export type SolutionCode = "code" | "report" | "nanogrid";

export interface SolutionMenu {
  /** 이동할 경로 */
  path: string;
  labelKey: StringKey;
  descKey: StringKey;
  /** 이 항목이 활성인지 판정할 경로 접두사 */
  match: string;
  /** 한 화면의 탭을 각각 메뉴로 낼 때, 이 메뉴가 맡는 탭들.
   *  없으면 그 경로 전체를 맡는다 — 지정하지 않으면 `/kb` 와 `/kb/checklist` 가
   *  동시에 활성으로 보인다. */
  tabs?: string[];
  /** 업무 흐름의 몇 번째 단계인가. 메뉴를 '기능 목록' 이 아니라 '순서' 로 읽히게 한다. */
  step?: number;
  /** 이 메뉴의 상태를 어느 지표에서 가져올지. 사이드바에서 진행 상태를 함께 보여준다. */
  statusKey?: "wiki" | "review" | "checklist";
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
  /** 메뉴에 노출하지 않는다. 개발이 끝나지 않은 솔루션을 지우지 않고 감추기 위한 것 —
   *  경로로 직접 들어가면 여전히 동작하므로 개발·시연에는 쓸 수 있다. */
  hidden?: boolean;
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
      {
        path: "/kb", labelKey: "kbLink", descKey: "solReportMenuKbDesc", match: "/kb",
        tabs: ["analyze", "documents", "search"], step: 2, statusKey: "wiki",
      },
      { path: "/wiki", labelKey: "wikiLink", descKey: "solReportMenuWikiDesc", match: "/wiki", step: 4, statusKey: "wiki" },
      { path: "/admin", labelKey: "adminLink", descKey: "solReportMenuAdminDesc", match: "/admin", step: 5, statusKey: "review" },
    ],
    engines: ["sllm", "grok", "rag", "aigov"],
  },
  {
    // 나노그리드 데이터 지식화 — 실시간·예측 데이터를 지식DB로 쌓고 AI 인사이트를
    // 위키로 서비스한다. 메뉴는 그룹·세부메뉴가 있어 NgSection 컴포넌트가 그린다.
    code: "nanogrid",
    labelKey: "solNgName",
    taglineKey: "solNgTagline",
    home: "/ng/monitor",
    menus: [],
    engines: ["sllm", "grok", "aigov"],
    // 개발이 끝나면 이 줄만 지우면 메뉴에 다시 나온다.
    hidden: true,
  },
];

/** 경로가 어느 솔루션에 속하는가. 솔루션을 별도 상태로 들지 않는 이유는,
 *  주소창으로 바로 들어온 사람과 메뉴로 들어온 사람이 다른 화면을 보면 안 되기 때문이다. */
export function solutionOf(path: string): SolutionCode {
  if (path.startsWith("/ng")) {
    return "nanogrid";
  }
  if (path.startsWith("/kb") || path.startsWith("/wiki") || path.startsWith("/admin")) {
    return "report";
  }
  return "code";
}

export function solution(code: SolutionCode): Solution {
  return SOLUTIONS.find((s) => s.code === code) ?? SOLUTIONS[0];
}


/** 메뉴에 그릴 솔루션. `hidden` 은 코드를 지우지 않고 노출만 막는다. */
export const VISIBLE_SOLUTIONS: Solution[] = SOLUTIONS.filter((s) => !s.hidden);
