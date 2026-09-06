/** 로그인 — 역할이 어디서 오는지 보이는 자리.
 *
 * 회의에서 정해진 것은 **SSO 다**.
 *
 *   "로그인 화면이 별도로 있기는 해야 되는데 SSO 로 다 처리할 겁니다. ...
 *    저희 시스템들이 다 별도 로그인은 있고 투 팩터 인증해가지고 아이디 여기
 *    OTP 입력하고 다 그 구조로 되어 있어서"
 *
 * 그래서 이 화면은 **자리를 잡아 두는 것**이지 인증을 하는 것이 아니다.
 * 지금은 고른 사람이 곧 그 역할이 되고, 사내 포털이 붙으면 이 화면 대신
 * SSO 가 같은 값을 내려 준다 — 역할 코드를 화면 문구가 아니라 역할 자체로
 * 지어 둔 이유가 이것이다.
 *
 * ★ 이것을 인증이라고 말하지 않는다. 화면에 그렇게 적어 둔다. 목업의 로그인을
 *   진짜 로그인으로 오해하면, 접근 통제가 이미 있는 줄 알고 넘어간다.
 */
import { useState } from "react";
import { ROLES, role as roleOf, type RoleCode } from "./roles";
import { useLang, LANGS, type Lang } from "./i18n";

export default function Login({
  onEnter,
  lang,
  setLang,
  base,
}: {
  onEnter: (who: string, role: RoleCode) => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  /** 로고 경로. 하위 경로 배포에서도 깨지지 않게 App 이 준다. */
  base: string;
}) {
  const { t } = useLang();
  const [who, setWho] = useState("");
  const [picked, setPicked] = useState<RoleCode>("governance");

  const enter = () => onEnter(who.trim() || t("lgAnonymous"), picked);

  return (
    <div className="lg">
      <form
        className="lg-card"
        onSubmit={(e) => {
          e.preventDefault();
          enter();
        }}
      >
        <div className="lg-brand">
          <img src={`${base}/gng-logo.png`} alt="GnG" />
          <div>
            <h1>{t("lgTitle")}</h1>
            <p className="muted small">{t("lgSub")}</p>
          </div>
          <div className="lg-lang">
            {LANGS.map((l) => (
              <button
                key={l}
                type="button"
                className={l === lang ? "active" : ""}
                onClick={() => setLang(l)}
              >
                {l.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <label className="lg-field">
          <span>{t("lgWho")}</span>
          <input
            value={who}
            onChange={(e) => setWho(e.target.value)}
            placeholder={t("lgWhoHint")}
            autoFocus
          />
        </label>

        <fieldset className="lg-roles">
          <legend>{t("lgRole")}</legend>
          {ROLES.map((r) => (
            <label key={r.code} className={picked === r.code ? "on" : ""}>
              <input
                type="radio"
                name="role"
                checked={picked === r.code}
                onChange={() => setPicked(r.code)}
              />
              <span>
                <b>{t(r.labelKey)}</b>
                <span className="muted small">{t(r.descKey)}</span>
              </span>
              {/* 사외 역할은 인사 테이블이 아니라 별도 등록에서 온다 —
                  연동할 때 이 둘을 다르게 다뤄야 한다는 표시다. */}
              {r.external && <span className="chip">{t("lgExternal")}</span>}
            </label>
          ))}
        </fieldset>

        <button className="btn lg-go" type="submit">
          {t("lgEnter").replace("{role}", t(roleOf(picked).labelKey))}
        </button>

        {/* 이것이 인증이 아니라는 것을 감추지 않는다. */}
        <p className="lg-note">{t("lgNotAuth")}</p>
      </form>
    </div>
  );
}
