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
import type { RoleCode } from "./roles";

export type SolutionCode = "code" | "compliance" | "report" | "nanogrid";

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
  /** 이 메뉴를 실제로 쓰는 역할. 비우면 모든 역할이 본다.
   *  회의 피드백("너무 많고 복잡하다")에 대한 답이다 — 한 사람이 자기 일과
   *  상관없는 메뉴까지 다 보고 있으면 어디서부터 손댈지 알 수 없다. */
  roles?: RoleCode[];
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
    home: "/programs",
    menus: [
      { path: "/programs", labelKey: "solCodeMenuPrograms", descKey: "solCodeMenuProgramsDesc",
        match: "/p/", roles: ["developer", "operator", "admin"] },
      { path: "/tables", labelKey: "tablesLink", descKey: "solCodeMenuTablesDesc",
        match: "/tables", roles: ["developer", "operator", "admin"] },
    ],
    engines: ["grok", "sllm", "aigov"],
  },
  {
    // 규제 준수 평가 — 소스 분석과 대상도 사용자도 다르다. 저쪽은 프로그램이
    // 탐색 단위이고 여기는 **서비스**가 탐색 단위다. 한 사이드바에 섞으면
    // "테이블 목록" 옆에 "커밋 결재"가 붙어 순서가 생기지 않는다.
    code: "compliance",
    labelKey: "solRegName",
    taglineKey: "solRegTagline",
    home: "/reg/overview",
    menus: [
      // 개요가 맨 위다 — 처음 온 사람이 메뉴를 눌러 보며 구조를 짐작하게 두지 않는다.
      { path: "/reg/overview", labelKey: "regTabOverview", descKey: "solRegMenuOverviewDesc",
        match: "/reg", tabs: ["overview"] },
      // 앞의 것이 없으면 뒤의 것이 의미가 없는 순서다. 번호가 그 사실을 말한다.
      // 업무 프로세스가 맨 위다 — 무엇을 할지 정하기 전에 어디가 막혔는지를 본다.
      { path: "/reg/process", labelKey: "regTabProcess", descKey: "solRegMenuProcessDesc",
        match: "/reg", tabs: ["process"], step: 1 },   // 현황은 전원이 본다
      { path: "/reg/services", labelKey: "regTabServices", descKey: "solRegMenuServicesDesc",
        match: "/reg", tabs: ["services"], step: 2,
        roles: ["planner", "admin"] },
      { path: "/reg/risk", labelKey: "riskTabRisk", descKey: "solRegMenuRiskDesc",
        match: "/reg", tabs: ["risk"], step: 3,
        // 위험 식별·경감은 기획이 적고 개발이 이행한다.
        roles: ["planner", "developer", "admin"] },
      // 결재 — 계획 승인과 결과 승인. 상신하는 쪽과 결정하는 쪽이 모두 본다.
      { path: "/reg/approvals", labelKey: "regTabApprovals", descKey: "solRegMenuApprovalsDesc",
        match: "/reg", tabs: ["approvals"], step: 4,
        roles: ["planner", "governance", "committee", "verifier", "admin"] },
      // 운영 — 배포 후 데이터 점검. 설계 단계에서도 같은 화면을 쓴다.
      { path: "/reg/ops", labelKey: "regTabOps", descKey: "solRegMenuOpsDesc",
        match: "/reg", tabs: ["ops"],
        roles: ["operator", "developer", "planner", "governance", "admin"] },
      { path: "/reg", labelKey: "regTabAssess", descKey: "solRegMenuAssessDesc",
        match: "/reg", tabs: ["assess"], step: 5,
        roles: ["governance", "committee", "verifier", "admin"] },
      // 아래 넷은 단계가 아니라 조직 전체를 보는 축이라 번호를 붙이지 않는다.
      // 기준 관리가 커버리지 앞에 온다 — 갭을 보기 전에 무엇을 기준으로 재는지가 먼저다.
      { path: "/reg/controls", labelKey: "regTabControls", descKey: "solRegMenuControlsDesc",
        match: "/reg", tabs: ["controls"],
        // 기준을 만드는 것은 거버넌스 담당자의 일이다.
        roles: ["governance", "admin"] },
      // 평가표 — 사람이 채우는 질문지. 기준 관리(기계가 확인하는 통제)와 나란히 둔다.
      { path: "/reg/sheets", labelKey: "regTabSheets", descKey: "solRegMenuSheetsDesc",
        match: "/reg", tabs: ["sheets"],
        roles: ["governance", "admin"] },
      { path: "/reg/coverage", labelKey: "regTabCoverage", descKey: "solRegMenuCoverageDesc",
        match: "/reg", tabs: ["coverage"],
        roles: ["governance", "admin"] },
      { path: "/reg/changes", labelKey: "regTabChanges", descKey: "solRegMenuChangesDesc",
        match: "/reg", tabs: ["changes"],
        // 고위험은 윤리위원회가, 저·중위험은 거버넌스 담당자가 승인한다.
        roles: ["governance", "committee", "admin"] },
      { path: "/reg/graph", labelKey: "regTabGraph", descKey: "solRegMenuGraphDesc",
        match: "/reg", tabs: ["graph"],
        // 감사 대응용. 평상시 업무 메뉴가 아니다.
        roles: ["governance", "admin"] },
    ],
    engines: ["sllm", "aigov", "grok"],
  },
  {
    code: "report",
    labelKey: "solReportName",
    taglineKey: "solReportTagline",
    home: "/kb",
    // 앞 화면은 소스 분석과 규제 준수 평가 둘로 간다. 이 솔루션은 지우지 않고
    // 노출만 막는다 — /kb · /wiki · /admin 로 직접 들어가면 그대로 동작한다.
    menus: [
      {
        path: "/kb", labelKey: "kbLink", descKey: "solReportMenuKbDesc", match: "/kb",
        tabs: ["analyze", "documents", "search"], step: 2, statusKey: "wiki",
      },
      { path: "/wiki", labelKey: "wikiLink", descKey: "solReportMenuWikiDesc", match: "/wiki", step: 4, statusKey: "wiki" },
      { path: "/admin", labelKey: "adminLink", descKey: "solReportMenuAdminDesc", match: "/admin", step: 5, statusKey: "review" },
    ],
    engines: ["sllm", "grok", "rag", "aigov"],
    hidden: true,
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
  // 서비스 대시보드(/svc/<id>)는 경로가 달라도 규제 축이다.
  // 루트도 여기다 — 첫 화면이 규제 축의 개요이므로, 사이드바가 소스 분석을
  // 보이면 본문과 사이드바가 서로 다른 제품을 말한다.
  if (path === "/" || path === "" || path.startsWith("/reg") || path.startsWith("/svc")) {
    return "compliance";
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


/** 이 역할이 볼 메뉴만 남긴다. `all` 이면 그대로 둔다.
 *  역할이 지정되지 않은 메뉴(업무 프로세스 등)는 모두가 본다 — 현황은 공통이다. */
export function menusFor(sol: Solution, roleCode: RoleCode): SolutionMenu[] {
  return sol.menus.filter((m) => !m.roles || m.roles.includes(roleCode));
}

/** 이 역할이 쓸 솔루션만 남긴다. 메뉴가 하나도 안 남으면 그 솔루션은 감춘다. */
export function solutionsFor(list: Solution[], roleCode: RoleCode): Solution[] {
  return list.filter((s) => menusFor(s, roleCode).length > 0);
}
