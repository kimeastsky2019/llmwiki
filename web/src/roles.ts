/** 참여자 역할 — 회의(2026-09-05)에서 정리된 AI RMF 상의 롤.
 *
 *   "저희가 사용자라고 할 게 RMF상의 롤이 있거든요. 개발자 기획자 그다음에
 *    운영자 그다음에 거버넌스 담당자 거기에 추가되는 게 임원들이나 관리자"
 *
 * 여기에 회의에서 따로 다룬 둘을 더한다.
 *
 *   · **AI 윤리위원회** — 내부 조직도에 없고("위원회 같은 경우에는 저게 내부
 *     조직도에 없잖아요") 이슈가 있을 때만 열리며, 고위험 건의 승인권자다.
 *   · **제3자 검증기관** — 외부다. "고위험 같은 경우에는 제3자 검증이 있어야
 *     되는 거고", 검증 결과를 등록하는 주체다.
 *
 * ★ 지금은 **화면을 줄이는 필터이지 접근 통제가 아니다.**
 *   사내 포털과 연동되면 이 값은 사람이 고르는 것이 아니라 로그인 권한에서
 *   내려온다. 그때 서버가 같은 코드로 판단하도록 코드 이름을 화면 문구가 아니라
 *   역할 자체로 지어 둔다 — 라벨이 바뀌어도 연동이 깨지지 않는다.
 */
import type { StringKey } from "./i18n";

export type RoleCode =
  | "governance"
  | "planner"
  | "developer"
  | "operator"
  | "committee"
  | "verifier"
  | "admin";

export interface Role {
  code: RoleCode;
  labelKey: StringKey;
  /** 이 역할이 이 시스템에서 하는 일 한 줄 */
  descKey: StringKey;
  /** 사내 조직 밖의 역할. 연동 시 인사 테이블이 아니라 별도 등록에서 온다. */
  external?: boolean;
}

/** 순서는 화면에 그대로 나온다. 거버넌스가 맨 앞인 것은 이 시스템의 주인이
 *  거버넌스 담당자이기 때문이고, 기본값이기도 하다. */
export const ROLES: Role[] = [
  { code: "governance", labelKey: "roleGovernance", descKey: "roleGovernanceDesc" },
  { code: "planner", labelKey: "rolePlanner", descKey: "rolePlannerDesc" },
  { code: "developer", labelKey: "roleDeveloper", descKey: "roleDeveloperDesc" },
  { code: "operator", labelKey: "roleOperator", descKey: "roleOperatorDesc" },
  // 아래 둘은 상설 조직이 아니다 — 위원회는 이슈 때만, 검증기관은 사외다.
  { code: "committee", labelKey: "roleCommittee", descKey: "roleCommitteeDesc", external: true },
  { code: "verifier", labelKey: "roleVerifier", descKey: "roleVerifierDesc", external: true },
  { code: "admin", labelKey: "roleAdmin", descKey: "roleAdminDesc" },
];

export const DEFAULT_ROLE: RoleCode = "governance";

const ROLE_KEY = "llmwiki.role";

export function readRole(): RoleCode {
  try {
    const saved = localStorage.getItem(ROLE_KEY) as RoleCode | null;
    return saved && ROLES.some((r) => r.code === saved) ? saved : DEFAULT_ROLE;
  } catch {
    return DEFAULT_ROLE;
  }
}

export function storeRole(code: RoleCode): void {
  try {
    localStorage.setItem(ROLE_KEY, code);
  } catch {
    /* 저장 못 해도 이번 세션에는 적용된다 */
  }
}

export function role(code: RoleCode): Role {
  return ROLES.find((r) => r.code === code) ?? ROLES[0];
}


/** 역할이 파이프라인에서 맡는 단계와, 그 역할이 할 일.
 *
 * 개요 그림을 역할마다 따로 그리지 않는다. 파이프라인은 하나뿐인데 그림이
 * 일곱 장이면 고칠 때 서로 어긋나고, 어긋난 그림은 아무도 믿지 않는다.
 * 대신 **같은 그림 위에서 그 역할이 만지는 단계만 살린다.**
 */
export interface RoleGuide {
  /** 파이프라인에서 이 역할이 맡는 단계 (Overview 의 카드 키) */
  owns: string[];
  /** 이 역할이 실제로 누르는 순서. 개요에서 바로 들어갈 수 있게 경로를 준다. */
  steps: { labelKey: StringKey; descKey: StringKey; path: string }[];
}

export const GUIDES: Record<RoleCode, RoleGuide> = {
  governance: {
    owns: ["controls", "assess"],
    steps: [
      { labelKey: "gvS1", descKey: "gvS1D", path: "/reg/controls" },
      { labelKey: "gvS2", descKey: "gvS2D", path: "/reg/sheets" },
      { labelKey: "gvS3", descKey: "gvS3D", path: "/reg" },
      { labelKey: "gvS4", descKey: "gvS4D", path: "/reg/changes" },
    ],
  },
  planner: {
    owns: ["define", "grade"],
    steps: [
      { labelKey: "plS1", descKey: "plS1D", path: "/reg/services" },
      { labelKey: "plS2", descKey: "plS2D", path: "/reg/selfcheck" },
      { labelKey: "plS3", descKey: "plS3D", path: "/reg/risk" },
      { labelKey: "plS4", descKey: "plS4D", path: "/reg/approvals" },
    ],
  },
  developer: {
    owns: ["grade", "controls"],
    steps: [
      // 소스 분석이 개발자의 출발점이다 — 코드에서 나온 사실이 위험 식별의 근거다.
      { labelKey: "dvS1", descKey: "dvS1D", path: "/programs" },
      { labelKey: "dvS2", descKey: "dvS2D", path: "/data" },
      { labelKey: "dvS3", descKey: "dvS3D", path: "/reg/risk" },
      { labelKey: "dvS4", descKey: "dvS4D", path: "/reg/selfcheck" },
    ],
  },
  operator: {
    owns: [],
    steps: [
      { labelKey: "opS1", descKey: "opS1D", path: "/data" },
      { labelKey: "opS2", descKey: "opS2D", path: "/reg/selfcheck" },
      { labelKey: "opS3", descKey: "opS3D", path: "/programs" },
      { labelKey: "opS4", descKey: "opS4D", path: "/reg/process" },
    ],
  },
  committee: {
    owns: ["confirm"],
    steps: [
      { labelKey: "cmS1", descKey: "cmS1D", path: "/reg/approvals" },
      { labelKey: "cmS2", descKey: "cmS2D", path: "/reg" },
      { labelKey: "cmS3", descKey: "cmS3D", path: "/reg/process" },
    ],
  },
  verifier: {
    owns: ["confirm"],
    steps: [
      { labelKey: "vfS1", descKey: "vfS1D", path: "/reg/approvals" },
      { labelKey: "vfS2", descKey: "vfS2D", path: "/reg" },
    ],
  },
  admin: {
    owns: ["define", "grade", "controls", "assess", "confirm"],
    steps: [
      { labelKey: "adS1", descKey: "adS1D", path: "/reg/process" },
      { labelKey: "adS2", descKey: "adS2D", path: "/reg/controls" },
      { labelKey: "adS3", descKey: "adS3D", path: "/programs" },
      { labelKey: "adS4", descKey: "adS4D", path: "/reg/graph" },
    ],
  },
};

export function guide(code: RoleCode): RoleGuide {
  return GUIDES[code] ?? GUIDES.governance;
}
