/** 로그인 — 아이디·비밀번호를 서버가 확인한다.
 *
 * 회의에서 정해진 최종 모습은 SSO 다("SSO 로 다 처리할 겁니다"). 이 화면은 그
 * 전까지 쓰는 것이고, 포털이 붙으면 SSO 가 같은 값(사람·역할)을 내려 준다.
 *
 * 화면에서만 통과시키지 않는다 — 검사는 `/api/auth/login` 에서 하고, 비밀번호는
 * 해시로만 저장한다(PBKDF2-SHA256). 화면 검사는 검사가 아니다.
 *
 * ★ 다만 이것은 **로그인이지 권한 검사가 아니다.** 들어온 뒤 각 API 가 "이
 *   사람이 이걸 해도 되나" 를 묻지 않는다. 그 사실을 화면 아래에 적어 둔다 —
 *   목업의 로그인을 진짜 접근 통제로 오해하면 없는 방어를 있다고 믿게 된다.
 */
import { useState } from "react";
import { api } from "./api";
import { useLang, LANGS, type Lang } from "./i18n";
import { ROLES, DEFAULT_ROLE, type RoleCode } from "./roles";

/** 서버가 준 역할 코드를 화면이 아는 코드로만 받는다. 모르는 값이 오면
 *  기본 역할로 떨어뜨린다 — 모르는 코드를 그대로 쓰면 메뉴가 텅 빈다. */
function asRole(code: string): RoleCode {
  return ROLES.some((r) => r.code === code) ? (code as RoleCode) : DEFAULT_ROLE;
}

/** 왼쪽 패널에 나열하는 흐름. 이 제품이 무엇을 도는지 한 줄로 말한다. */
const FLOW = ["lgChip1", "lgChip2", "lgChip3", "lgChip4", "lgChip5"] as const;

export default function Login({
  onEnter,
  lang,
  setLang,
  base,
}: {
  onEnter: (who: string, role: RoleCode, remember: boolean) => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  /** 로고 경로. 하위 경로 배포에서도 깨지지 않게 App 이 준다. */
  base: string;
}) {
  const { t } = useLang();
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    api
      .login(id, password)
      .then((r) => onEnter(r.name || r.id, asRole(r.role), remember))
      .catch((err) => setError(String(err instanceof Error ? err.message : err)))
      .finally(() => setBusy(false));
  };

  return (
    <div className="lg">
      <div className="lg-card">
        {/* ── 왼쪽: 브랜드 ─────────────────────────────────────────── */}
        <aside className="lg-brand">
          <header>
            <img src={`${base}/gng-logo.png`} alt="" />
            <div>
              <b>{t("lgOrg")}</b>
              <span>{t("lgOrgSub")}</span>
            </div>
          </header>

          <div className="lg-brand-body">
            <h1>{t("lgHeadline")}</h1>
            <p>{t("lgBlurb")}</p>
            <ul className="lg-chips">
              {FLOW.map((k) => (
                <li key={k}>{t(k)}</li>
              ))}
            </ul>
          </div>
        </aside>

        {/* ── 오른쪽: 폼 ───────────────────────────────────────────── */}
        <form className="lg-form" onSubmit={submit}>
          <div className="lg-form-head">
            <div>
              <h2>{t("lgTitle")}</h2>
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
            <span>{t("lgId")}</span>
            <input
              value={id}
              onChange={(e) => setId(e.target.value)}
              placeholder={t("lgIdHint")}
              autoComplete="username"
              autoFocus
            />
          </label>

          <label className="lg-field">
            <span>{t("lgPw")}</span>
            <span className="lg-pw">
              <input
                type={show ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t("lgPwHint")}
                autoComplete="current-password"
              />
              <button
                type="button"
                className="lg-eye"
                onClick={() => setShow((v) => !v)}
                aria-label={t(show ? "lgHide" : "lgShow")}
                title={t(show ? "lgHide" : "lgShow")}
              >
                {show ? "◡" : "◉"}
              </button>
            </span>
          </label>

          <div className="lg-row">
            <label className="lg-keep">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              <span>{t("lgRemember")}</span>
            </label>
            {/* 비밀번호 재설정 경로가 아직 없다. 없는 것을 링크로 두면 눌러 보고
                막힌다 — 어디로 물어야 하는지를 대신 말한다. */}
            <span className="lg-forgot" title={t("lgForgotHint")}>
              {t("lgForgot")}
            </span>
          </div>

          {error && <div className="banner error lg-error">{error}</div>}

          <button className="btn lg-go" type="submit" disabled={busy}>
            {busy ? "…" : `${t("lgEnter")}  →`}
          </button>

          <footer className="lg-foot">
            <span className="muted small">{t("lgCopy")}</span>
            <span className="muted small mono">{t("lgHost")}</span>
          </footer>

          {/* 이것이 권한 검사가 아니라는 것을 감추지 않는다. */}
          <p className="lg-note">{t("lgNotAuthz")}</p>
        </form>
      </div>
    </div>
  );
}
