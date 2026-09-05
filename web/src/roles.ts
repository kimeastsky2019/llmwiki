/** 참여자 역할 — 회의(2026-09-05)에서 정리된 AI RMF 상의 롤.
 *
 *   "저희가 사용자라고 할 게 RMF상의 롤이 있거든요. 개발자 기획자 그다음에
 *    운영자 그다음에 거버넌스 담당자 거기에 추가되는 게 임원들이나 관리자"
 *
 * 여기에 회의에서 따로 다룬 **AI 윤리위원회**를 더한다. 위원회는 내부 조직도에
 * 없고("위원회 같은 경우에는 저게 내부 조직도에 없잖아요") 이슈가 있을 때만
 * 열리며, 고위험 건의 승인권자다.
 *
 * ★ 이것은 **화면을 줄이는 필터이지 접근 통제가 아니다.**
 *   실제 권한은 SSO·인사 테이블 연동 위에서 서버가 판단해야 한다(회의: "결제했을
 *   때에는 조직도랑 연계가 돼야 되잖아요"). 그 연동이 붙기 전에 이 선택을
 *   권한처럼 보이게 하면, 안 보이니까 못 한다고 오해하게 된다. 화면도 그렇게
 *   말하지 않는다.
 */
import type { StringKey } from "./i18n";

export type RoleCode =
  | "all"
  | "planner"
  | "developer"
  | "operator"
  | "governance"
  | "committee"
  | "admin";

export interface Role {
  code: RoleCode;
  labelKey: StringKey;
  /** 이 역할이 이 시스템에서 하는 일 한 줄 */
  descKey: StringKey;
}

/** 순서는 업무가 흘러가는 순서다 — 기획 → 개발 → 운영, 그리고 그것을 받는 쪽. */
export const ROLES: Role[] = [
  { code: "all", labelKey: "roleAll", descKey: "roleAllDesc" },
  { code: "planner", labelKey: "rolePlanner", descKey: "rolePlannerDesc" },
  { code: "developer", labelKey: "roleDeveloper", descKey: "roleDeveloperDesc" },
  { code: "operator", labelKey: "roleOperator", descKey: "roleOperatorDesc" },
  { code: "governance", labelKey: "roleGovernance", descKey: "roleGovernanceDesc" },
  { code: "committee", labelKey: "roleCommittee", descKey: "roleCommitteeDesc" },
  { code: "admin", labelKey: "roleAdmin", descKey: "roleAdminDesc" },
];

const ROLE_KEY = "llmwiki.role";

export function readRole(): RoleCode {
  try {
    const saved = localStorage.getItem(ROLE_KEY) as RoleCode | null;
    return saved && ROLES.some((r) => r.code === saved) ? saved : "all";
  } catch {
    return "all";
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
