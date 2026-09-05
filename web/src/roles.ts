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
