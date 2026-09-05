/** 결재 — 계획 승인과 결과 승인, 두 차례.
 *
 * 화면이 역할에 따라 다르게 보인다. 같은 목록을 놓고 "당신이 할 수 있는 것"만
 * 남기는 것이 아니라, 애초에 **볼 수 있는 것이 다르다** —
 *
 *   · AI 윤리위원회 / AI 거버넌스 — 자기가 승인권자인 건만
 *   · 제3자 검증기관 — 자기가 검증할 건만 (사외라서 사내 서비스 목록 전체가
 *     열리면 안 된다). 그리고 여기서 하는 것은 승인이 아니라 결과 등록이다.
 *   · 그 밖 — 상신과 현황
 *
 * 서버가 같은 규칙으로 한 번 더 거른다. 화면에서만 감추면 주소를 아는 사람은
 * 그대로 볼 수 있다.
 */
import { useCallback, useEffect, useState } from "react";
import { api, type RegApproval } from "./api";
import { useLang, type StringKey } from "./i18n";
import type { RoleCode } from "./roles";

const SIGNER_KEY = "llmwiki.reg.signer";

function readSigner(): string {
  try {
    return localStorage.getItem(SIGNER_KEY) ?? "gov-officer";
  } catch {
    return "gov-officer";
  }
}

const KIND_LABEL: Record<string, StringKey> = {
  plan: "apKindPlan",
  result: "apKindResult",
};

const STATUS_CLASS: Record<string, string> = {
  pending: "s-pending",
  approved: "s-ok",
  rejected: "s-rejected",
};

export default function Approvals({ roleCode }: { roleCode: RoleCode }) {
  const { t } = useLang();
  const [rows, setRows] = useState<RegApproval[] | null>(null);
  const [who, setWho] = useState(readSigner);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    api.reg
      .approvals(roleCode)
      .then((r) => setRows(r.approvals))
      .catch((e) => setError(String(e)));
  }, [roleCode]);
  useEffect(load, [load]);

  const act = (fn: Promise<unknown>) => {
    fn.then(() => {
      try {
        localStorage.setItem(SIGNER_KEY, who);
      } catch {
        /* 저장 못 해도 처리는 됐다 */
      }
      load();
    }).catch((e) => setError(String(e)));
  };

  const isVerifier = roleCode === "verifier";
  const canDecide = roleCode === "committee" || roleCode === "governance";

  return (
    <section className="ap">
      <header className="svc-head">
        <div>
          <h2>{t("apTitle")}</h2>
          <p className="lede">{t(isVerifier ? "apLedeVerifier" : "apLede")}</p>
        </div>
        <label className="reg-signer">
          <span>{t(isVerifier ? "apVerifier" : "apSigner")}</span>
          <input value={who} onChange={(e) => setWho(e.target.value)} />
        </label>
      </header>

      {error && <div className="banner error">{error}</div>}

      {/* 등급이 승인권자를 정한다는 것을 목록 위에서 한 번 말한다 — 표만 보면
          왜 어떤 건은 내가 못 누르는지 알 수 없다. */}
      <div className="banner note">{t("apRuleNote")}</div>

      {rows === null ? (
        <div className="muted pad">…</div>
      ) : rows.length === 0 ? (
        <div className="muted pad">{t(isVerifier ? "apEmptyVerifier" : "apEmpty")}</div>
      ) : (
        <div className="ap-list">
          {rows.map((r) => (
            <article key={r.approval_id} className="ap-card">
              <header>
                <span className={`chip ${STATUS_CLASS[r.status] ?? ""}`}>
                  {t(`apStatus_${r.status}` as StringKey)}
                </span>
                <b>{r.service_name}</b>
                <span className="chip">{t(KIND_LABEL[r.kind] ?? "apKindPlan")}</span>
                {r.grade_label && <span className="muted small">{r.grade_label}</span>}
              </header>

              <p className="muted small">
                {t("apRequested")
                  .replace("{who}", r.requested_by)
                  .replace("{at}", (r.requested_at || "").slice(0, 16).replace("T", " "))}
                {" · "}
                {t("apApprover").replace("{role}", t(`role_${r.approver_role}` as StringKey))}
              </p>
              {r.note && <p className="ap-note">{r.note}</p>}

              {/* 제3자 검증 — 고위험 결과 승인에만 붙는다 */}
              {r.needs_verification && (
                <div className={`ap-verify ${r.verification ? "done" : ""}`}>
                  {r.verification ? (
                    <span>
                      <b>{t(r.verification.result === "pass" ? "apVerPass" : "apVerFail")}</b>{" "}
                      <span className="muted small">
                        {r.verification.by} · {(r.verification.at || "").slice(0, 16).replace("T", " ")}
                      </span>
                      {r.verification.note && <div className="muted small">{r.verification.note}</div>}
                    </span>
                  ) : (
                    <span className="muted small">{t("apVerWaiting")}</span>
                  )}
                </div>
              )}

              {/* 검증기관은 결과만 등록한다 — 승인 버튼이 없다 */}
              {isVerifier && r.status === "pending" && !r.verification && (
                <div className="ap-actions">
                  <button
                    className="btn"
                    onClick={() => act(api.reg.verify(r.approval_id, who, "pass"))}
                  >
                    {t("apFilePass")}
                  </button>
                  <button
                    className="btn ghost"
                    onClick={() => act(api.reg.verify(r.approval_id, who, "fail"))}
                  >
                    {t("apFileFail")}
                  </button>
                  <span className="muted small">{t("apVerNotApproval")}</span>
                </div>
              )}

              {canDecide && r.status === "pending" && (
                <div className="ap-actions">
                  <button
                    className="btn"
                    onClick={() => act(api.reg.decide(r.approval_id, who, roleCode, true))}
                  >
                    {t("apApprove")}
                  </button>
                  <button
                    className="btn ghost"
                    onClick={() => act(api.reg.decide(r.approval_id, who, roleCode, false))}
                  >
                    {t("apReject")}
                  </button>
                </div>
              )}

              {r.status !== "pending" && (
                <p className="muted small">
                  {t("apDecided")
                    .replace("{who}", r.decided_by)
                    .replace("{at}", (r.decided_at || "").slice(0, 16).replace("T", " "))}
                </p>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
