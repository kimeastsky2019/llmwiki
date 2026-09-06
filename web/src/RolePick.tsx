/** 역할 고르기 — 로그인 다음, 화면에 들어가기 전.
 *
 * 로그인은 "누구인지" 만 확인한다. 이 화면은 "어떤 일을 하러 왔는지" 를 묻는다.
 * 회의에서 나온 요구가 이것이었다 — 참여자 역할에 따라 메뉴가 정리되어야 한다.
 *
 *   "기획/서비스 구현 등 다양한 참여자의 역활에 따라 서비스가 정리 되었으면
 *    좋겠다. 너무 많고 복잡하다"
 *
 * 계정에 붙은 역할을 미리 골라 둔다(★ 표시). 그대로 눌러도 되고 바꿔도 된다 —
 * 한 사람이 기획도 하고 운영도 보는 조직이 많다.
 *
 * ★ 이것은 **보기 필터이지 권한이 아니다.** 다른 역할을 골라도 서버가 막지
 *   않는다. 사내 포털이 붙으면 이 값은 고르는 것이 아니라 로그인 권한에서
 *   내려온다 — 그때까지 없는 것을 있는 척하지 않는다.
 */
import { useState } from "react";
import { ROLES, role as roleOf, type RoleCode } from "./roles";
import { useLang } from "./i18n";

/** 조사 로/으로. 받침이 없거나 ㄹ 받침이면 '로', 아니면 '으로' —
 *  "관리자로", "AI 개발로", "AI 운영으로". 역할 이름이 바뀌어도 문장이
 *  어색해지지 않게 규칙으로 붙인다. */
function ro(word: string): string {
  const code = word.trim().charCodeAt(word.trim().length - 1) - 0xac00;
  if (code < 0 || code > 11171) return "로"; // 한글 음절이 아니면 그냥 '로'
  const jong = code % 28;
  return jong === 0 || jong === 8 ? "로" : "으로";
}

export default function RolePick({
  who,
  accountRole,
  onPick,
  onBack,
  base,
}: {
  /** 로그인한 사람 이름. 누구로 들어와 있는지 여기서도 보인다. */
  who: string;
  /** 계정에 지정된 역할. 기본 선택이 되고 ★ 로 표시된다. */
  accountRole: RoleCode;
  onPick: (role: RoleCode) => void;
  /** 잘못 들어왔을 때 로그인으로 돌아가는 길 */
  onBack: () => void;
  base: string;
}) {
  const { t } = useLang();
  const [picked, setPicked] = useState<RoleCode>(accountRole);

  return (
    <div className="lg">
      <form
        className="lg-card rp-card"
        onSubmit={(e) => {
          e.preventDefault();
          onPick(picked);
        }}
      >
        <div className="rp-head">
          <img src={`${base}/gng-logo.png`} alt="" />
          <div>
            <h2>{t("rpTitle")}</h2>
            <p className="muted small">{t("rpSub", { who })}</p>
          </div>
          <button type="button" className="rp-back" onClick={onBack}>
            {t("rpBack")}
          </button>
        </div>

        <fieldset className="lg-roles">
          <legend>{t("rpLegend")}</legend>
          {ROLES.map((r) => (
            <label key={r.code} className={picked === r.code ? "on" : ""}>
              <input
                type="radio"
                name="role"
                checked={picked === r.code}
                onChange={() => setPicked(r.code)}
              />
              <span>
                <b>
                  {t(r.labelKey)}
                  {/* 계정에 붙은 역할. 고르라고 두되 어느 것이 '내 것'인지는 알려 준다. */}
                  {r.code === accountRole && (
                    <span className="rp-mine" title={t("rpMineHint")}>
                      {t("rpMine")}
                    </span>
                  )}
                </b>
                <span className="muted small">{t(r.descKey)}</span>
              </span>
              {/* 사외 역할은 인사 테이블이 아니라 별도 등록에서 온다 —
                  연동할 때 이 둘을 다르게 다뤄야 한다는 표시다. */}
              {r.external && <span className="chip">{t("lgExternal")}</span>}
            </label>
          ))}
        </fieldset>

        <button className="btn lg-go" type="submit">
          {t("rpEnter", { role: t(roleOf(picked).labelKey), ro: ro(t(roleOf(picked).labelKey)) })}
        </button>

        {/* 필터일 뿐이라는 것을 감추지 않는다. */}
        <p className="lg-note">{t("rpNote")}</p>
      </form>
    </div>
  );
}
