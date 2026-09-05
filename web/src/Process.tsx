/** 업무 프로세스 — 단계별 적체와 지금 손댈 것을 한 화면에.
 *
 * 목업(2026-09-05 업로드본)의 'CONTROL TOWER / PROCESS VIEW' 를 옮긴 것이다.
 * 다만 목업이 보여 주던 칸 중 우리가 **기록하지 않는 것은 옮기지 않았다.**
 *
 *   · SLA(8h) · 마감 임박(2h 남음)  — 기한을 기록하는 곳이 없다. 뺐다.
 *   · 모니터링 커버리지 96%          — 운영 중 모델을 추적하는 장치가 없다.
 *                                     대신 실제로 재는 값(자동 판정률)을 쓴다.
 *   · 승인 리드타임                   — 결재의 created_at·reviewed_at 으로 계산할
 *                                     수 있어 남겼다. 표본이 없으면 '미측정'.
 *
 * 목업 그대로 칸을 채우면 숫자가 있는 것처럼 보이고, 그 숫자가 곧 근거가 된다.
 * 이 제품에서 그것은 가장 하면 안 되는 일이다.
 */
import { useCallback, useEffect, useState } from "react";
import { api, type RegProcess, type RegStage } from "./api";
import { useLang, type StringKey } from "./i18n";

/** 단계 라벨은 서비스 화면과 같은 문자열을 쓴다 — 두 화면이 같은 단계를
 *  다르게 부르면 같은 것인지 알 수 없다. */
const STAGE_LABEL: Record<RegStage, StringKey> = {
  define: "svcStageDefine",
  grade: "svcStageGrade",
  controls: "svcStageControls",
  assess: "svcStageAssess",
  confirm: "svcStageConfirm",
  done: "svcStageDone",
};

/** 단계 설명은 프로세스 전용이다. 서비스 화면의 '다음 할 일' 문구는 그 서비스의
 *  미확정 건수를 받아 쓰므로, 여러 서비스가 모이는 이 카드에는 맞지 않는다. */
const STAGE_DESC: Record<RegStage, StringKey> = {
  define: "procStageDefine",
  grade: "procStageGrade",
  controls: "procStageControls",
  assess: "procStageAssess",
  confirm: "procStageConfirm",
  done: "procStageDone",
};

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export default function Process({
  onNavigate,
}: {
  onNavigate: (path: string) => void;
}) {
  const { t } = useLang();
  const [data, setData] = useState<RegProcess | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.reg.process().then(setData).catch((e) => setError(String(e)));
  }, []);
  useEffect(load, [load]);

  if (error) return <div className="banner error">{error}</div>;
  if (!data) return <div className="muted pad">…</div>;

  const { kpi, controls } = data;
  // done 은 흐름 카드로 그리지 않는다 — 끝난 것은 단계가 아니다.
  const flow = data.stages.filter((s) => s.key !== "done");
  const done = data.stages.find((s) => s.key === "done");

  return (
    <section className="proc">
      <header className="svc-head">
        <div>
          <h2>{t("procTitle")}</h2>
          <p className="lede">{t("procLede")}</p>
        </div>
      </header>

      <div className="kpi-grid">
        <Kpi label={t("procKpiPending")} value={String(kpi.pending_changes)} unit={t("procUnitCase")}
             note={kpi.blocked_changes > 0
               ? t("procKpiBlocked").replace("{n}", String(kpi.blocked_changes))
               : t("procKpiNoBlocked")}
             tone={kpi.blocked_changes > 0 ? "warn" : "ok"} />
        <Kpi label={t("procKpiLead")}
             value={kpi.lead_time_days === null ? "—" : String(kpi.lead_time_days)}
             unit={kpi.lead_time_days === null ? "" : t("procUnitDay")}
             note={kpi.lead_time_samples === 0
               ? t("procKpiLeadNone")
               : t("procKpiLeadFrom").replace("{n}", String(kpi.lead_time_samples))} />
        <Kpi label={t("procKpiHighRisk")} value={String(kpi.high_risk)} unit={t("procUnitCase")}
             note={t("procKpiHighRiskNote")}
             tone={kpi.high_risk > 0 ? "warn" : "ok"} />
        <Kpi label={t("procKpiAuto")} value={pct(kpi.auto_rate)} unit=""
             note={t("procKpiDeferred").replace("{n}", String(kpi.deferred))} />
      </div>

      <div className="proc-panel">
        <div className="proc-panel-head">
          <div>
            <h3>{t("procFlow")}</h3>
            <p className="muted small">{t("procFlowLede")}</p>
          </div>
          {done && done.count > 0 && (
            <span className="chip s-ok">
              {t("procDone").replace("{n}", String(done.count))}
            </span>
          )}
        </div>

        <ol className="process-flow">
          {flow.map((stage, i) => (
            <li key={stage.key} className={`stage-card ${stage.count > 0 ? "busy" : ""}`}>
              <span className="stage-no">
                {String(i + 1).padStart(2, "0")} / {stage.key.toUpperCase()}
              </span>
              <h4>{t(STAGE_LABEL[stage.key])}</h4>
              <p className="muted small">{t(STAGE_DESC[stage.key])}</p>
              <ul className="stage-svcs">
                {stage.services.map((s) => (
                  <li key={s.uuid}>
                    <button className="linkish" onClick={() => onNavigate(`/svc/${s.uuid}`)}>
                      {s.name}
                    </button>
                    {s.grade && <span className="muted small"> · {s.grade}</span>}
                  </li>
                ))}
              </ul>
              <div className="stage-foot">
                <b>{stage.count}</b>
                <span className="muted small">{t("procUnitService")}</span>
              </div>
            </li>
          ))}
        </ol>

        <p className="proc-gate">
          <b>{t("procGate")}</b> {t("procGateNote")}
        </p>
      </div>

      <div className="proc-lower">
        <div className="proc-card">
          <div className="proc-panel-head">
            <div>
              <h3>{t("procQueue")}</h3>
              <p className="muted small">{t("procQueueLede")}</p>
            </div>
            <button className="btn ghost sm" onClick={() => onNavigate("/reg/changes")}>
              {t("procQueueAll")}
            </button>
          </div>
          {data.queue.length === 0 ? (
            <div className="muted pad">{t("procQueueEmpty")}</div>
          ) : (
            <ul className="task-list">
              {data.queue.map((q) => (
                <li key={`${q.kind}:${q.id}`}>
                  <span className={`chip ${q.kind === "blocked" ? "s-blocked" : q.kind === "pending" ? "s-pending" : ""}`}>
                    {t(q.kind === "blocked" ? "procKindBlocked"
                      : q.kind === "pending" ? "procKindPending" : "procKindStage")}
                  </span>
                  <button
                    className="linkish task-name"
                    onClick={() => onNavigate(q.kind === "stage" ? `/svc/${q.id}` : "/reg/changes")}
                  >
                    {q.title}
                  </button>
                  <span className="muted small task-owner">
                    {q.kind === "stage" && q.stage ? t(STAGE_LABEL[q.stage]) : q.owner}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {data.queue_total > data.queue.length && (
            <p className="muted small pad">
              {t("procQueueMore").replace("{n}", String(data.queue_total - data.queue.length))}
            </p>
          )}
        </div>

        <div className="proc-card">
          <div className="proc-panel-head">
            <div>
              <h3>{t("procControls")}</h3>
              <p className="muted small">{t("procControlsLede")}</p>
            </div>
            <b className="proc-rate">{pct(controls.rate)}</b>
          </div>
          <div className="meter">
            <span style={{ width: pct(controls.rate) }} />
          </div>
          <p className="muted small">
            {t("procControlsCount")
              .replace("{n}", String(controls.satisfied))
              .replace("{t}", String(controls.total))}
          </p>
          {/* 유보 사유는 '왜 자동으로 못 정했나' 다. 이게 다음에 손댈 것을 정한다. */}
          <ul className="check-list">
            {Object.entries(controls.triggers).map(([code, n]) => (
              <li key={code} className="check-item pending">
                <i />
                <span>
                  <code className="inline-code">{code}</code> {n}
                  {t("procUnitCase")}
                </span>
              </li>
            ))}
            {Object.keys(controls.triggers).length === 0 && (
              <li className="check-item">
                <i />
                <span>{t("procNoDeferral")}</span>
              </li>
            )}
          </ul>
          <button className="btn ghost sm" onClick={() => onNavigate("/reg")}>
            {t("procControlsGo")}
          </button>
        </div>
      </div>
    </section>
  );
}

function Kpi({
  label, value, unit, note, tone,
}: {
  label: string; value: string; unit: string; note: string; tone?: "ok" | "warn";
}) {
  return (
    <div className="kpi">
      <span className="label">{label}</span>
      <span className="value-row">
        <b>{value}</b>
        {unit && <small>{unit}</small>}
      </span>
      <small className={`trend ${tone ?? ""}`}>{note}</small>
    </div>
  );
}
