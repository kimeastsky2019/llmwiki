import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type RiskAdvice,
  type RiskAdvisor,
  type RiskInput,
  type RiskItemInput,
  type RiskMaster,
  type RiskResult,
  type RiskDraftRow,
} from "./api";
import { useLang } from "./i18n";

/**
 * AI 위험등급 산정 — STEP 1~5 마법사.
 *
 * 계산은 전부 서버(riskassess.py)가 한다. 이 화면은 입력만 모으고, 점수·등급은
 * 서버 응답을 그대로 보여 준다. 화면에서 다시 계산하면 두 벌이 되어 언젠가
 * 어긋나고, 어긋난 쪽이 화면이면 감리에서 설명할 수 없다.
 */
const STEPS = [1, 2, 3, 4, 5] as const;
export type StepNo = (typeof STEPS)[number];

/** 잔여 평가 코드 — 서버 마스터의 code 와 같은 값을 보낸다. */
const RESIDUAL_CODES = ["○", "△", "X"] as const;

const DRAFT_KEY = "llmwiki.risk.signer";

function readSigner(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? "";
  } catch {
    return "";
  }
}

function emptyInput(): RiskInput {
  return {
    service_uuid: "",
    service_name: "",
    high_impact_a: [],
    high_impact_b: [],
    safety: {},
    safety_stage: "",
    profile: {},
    items: [],
  };
}

/** 항목 입력을 번호로 찾는다. 없으면 '식별 안 함' 기본값. */
function itemOf(input: RiskInput, no: number): RiskItemInput {
  return (
    input.items.find((i) => i.no === no) ?? {
      no,
      identified: false,
      mitigated: false,
      residual: "X",
    }
  );
}

function fmt(n: number | null | undefined, decimals = 1): string {
  if (n === null || n === undefined) return "–";
  return Number.isInteger(n) ? String(n) : n.toFixed(decimals);
}

export default function RiskWizard() {
  const { t } = useLang();
  const [master, setMaster] = useState<RiskMaster | null>(null);
  const [input, setInput] = useState<RiskInput>(emptyInput);
  const [result, setResult] = useState<RiskResult | null>(null);
  const [step, setStep] = useState<StepNo>(1);
  const [drafts, setDrafts] = useState<RiskDraftRow[]>([]);
  const [signer, setSigner] = useState(readSigner);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.reg.risk.master().then(setMaster).catch((e) => setErr(e.message));
  }, []);

  const loadDrafts = useCallback(() => {
    api.reg.risk
      .drafts()
      .then((r) => setDrafts(r.drafts))
      .catch(() => undefined);
  }, []);
  useEffect(loadDrafts, [loadDrafts]);

  // 입력이 바뀔 때마다 서버에 다시 물어 본다. 계산이 가벼워 왕복해도 즉각적이고,
  // 무엇보다 화면과 서버가 다른 답을 낼 여지가 사라진다.
  useEffect(() => {
    let alive = true;
    api.reg.risk
      .assess(input)
      .then((r) => alive && setResult(r))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [input]);

  const patch = useCallback((next: Partial<RiskInput>) => {
    setInput((cur) => ({ ...cur, ...next }));
  }, []);

  const toggleIn = useCallback(
    (key: "high_impact_a" | "high_impact_b", id: string) => {
      setInput((cur) => {
        const have = cur[key].includes(id);
        return {
          ...cur,
          [key]: have ? cur[key].filter((x) => x !== id) : [...cur[key], id],
        };
      });
    },
    []
  );

  const setItem = useCallback((no: number, next: Partial<RiskItemInput>) => {
    setInput((cur) => {
      const rest = cur.items.filter((i) => i.no !== no);
      const merged = { ...itemOf(cur, no), ...next };
      return { ...cur, items: [...rest, merged].sort((a, b) => a.no - b.no) };
    });
  }, []);

  const save = async () => {
    if (!signer.trim()) {
      setErr(t("riskNeedSigner"));
      return;
    }
    if (!input.service_uuid?.trim()) {
      setErr(t("riskNeedService"));
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      localStorage.setItem(DRAFT_KEY, signer);
      await api.reg.risk.save(input.service_uuid, input, signer);
      loadDrafts();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const load = async (uuid: string) => {
    setErr(null);
    try {
      const draft = await api.reg.risk.draft(uuid);
      setInput({ ...emptyInput(), ...draft.input });
      setStep(1);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const drop = async (uuid: string) => {
    await api.reg.risk.remove(uuid).catch(() => undefined);
    loadDrafts();
  };

  if (!master) return <div className="page muted">{t("loading")}</div>;

  return (
    <div className="risk">
      <header className="risk-head">
        <div>
          <h1>{t("riskTitle")}</h1>
          <p className="lede">{t("riskLede")}</p>
        </div>
        <div className="risk-versions" title={Object.values(master.standard).join("\n")}>
          {t("riskMasterVersion", { v: master.version })}
        </div>
      </header>

      {master.invariant_problems.length > 0 && (
        <div className="banner error">
          {t("riskMasterBroken")}
          <ul>
            {master.invariant_problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      {err && <div className="banner error">{err}</div>}

      <StepBar step={step} onStep={setStep} result={result} />

      <div className="risk-body">
        <div className="risk-main">
          {step === 1 && (
            <Step1
              master={master}
              input={input}
              result={result}
              onToggle={toggleIn}
              onSafety={(id, on) =>
                patch({ safety: { ...input.safety, [id]: on } })
              }
              onStage={(v) => patch({ safety_stage: v })}
            />
          )}
          {step === 2 && (
            <Step2
              master={master}
              input={input}
              onProfile={(k, v) => patch({ profile: { ...input.profile, [k]: v } })}
              onService={(uuid, name) => patch({ service_uuid: uuid, service_name: name })}
            />
          )}
          {step === 3 && (
            <Step3 master={master} input={input} result={result} onItem={setItem} />
          )}
          {step === 4 && (
            <Step4 master={master} input={input} result={result} onItem={setItem} />
          )}
          {step === 5 && <Step5 master={master} result={result} />}
        </div>

        <aside className="risk-side">
          <ScorePanel result={result} decimals={master.rounding.display_decimals} />
          <div className="risk-save">
            <label className="risk-field">
              <span>{t("riskSigner")}</span>
              <input value={signer} onChange={(e) => setSigner(e.target.value)} />
            </label>
            <button className="btn" onClick={save} disabled={busy}>
              {t("riskSave")}
            </button>
          </div>
          <DraftList drafts={drafts} onLoad={load} onDrop={drop} />
        </aside>
      </div>

      <footer className="risk-foot">
        <button
          className="btn ghost"
          disabled={step === 1}
          onClick={() => setStep((s) => (s - 1) as StepNo)}
        >
          {t("riskPrev")}
        </button>
        <button
          className="btn"
          disabled={step === 5}
          onClick={() => setStep((s) => (s + 1) as StepNo)}
        >
          {t("riskNext")}
        </button>
      </footer>
    </div>
  );
}

// --------------------------------------------------------------------------
// 단계 표시줄
// --------------------------------------------------------------------------
function StepBar({
  step,
  onStep,
  result,
}: {
  step: StepNo;
  onStep: (s: StepNo) => void;
  result: RiskResult | null;
}) {
  const { t } = useLang();
  const labels: Record<StepNo, string> = {
    1: t("riskStep1"),
    2: t("riskStep2"),
    3: t("riskStep3"),
    4: t("riskStep4"),
    5: t("riskStep5"),
  };
  const done: Record<StepNo, boolean> = {
    1: (result?.step1_high_impact.a_count ?? 0) + (result?.step1_high_impact.b_count ?? 0) > 0,
    2: Object.keys(result?.step2_evaluation_set ? {} : {}).length >= 0,
    3: (result?.step3_recognized_score ?? 0) > 0,
    4: (result?.step4_residual_score ?? 0) !== (result?.step3_recognized_score ?? 0),
    5: false,
  };
  return (
    <ol className="step-bar">
      {STEPS.map((s) => (
        <li key={s} className={`step ${s === step ? "on" : ""} ${done[s] ? "done" : ""}`}>
          <button onClick={() => onStep(s)}>
            <span className="step-no">{s}</span>
            <span className="step-label">{labels[s]}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

// --------------------------------------------------------------------------
// STEP 1 — 고영향 / 안전성
// --------------------------------------------------------------------------
function Step1({
  master,
  input,
  result,
  onToggle,
  onSafety,
  onStage,
}: {
  master: RiskMaster;
  input: RiskInput;
  result: RiskResult | null;
  onToggle: (key: "high_impact_a" | "high_impact_b", id: string) => void;
  onSafety: (id: string, on: boolean) => void;
  onStage: (v: string) => void;
}) {
  const { t } = useLang();
  const high = result?.step1_high_impact;
  const safety = result?.step1_safety;

  return (
    <>
      <h2>{t("riskStep1")}</h2>
      <p className="risk-rule">
        {t("riskRule")}: <code>{master.high_impact.rule}</code>
        <span className="risk-src">{master.high_impact.source}</span>
      </p>
      {/* 배점을 합산하지 않는다는 것을 화면에도 적어 둔다 — 가장 흔한 오해다 */}
      <div className="banner note">{t("riskNotASum")}</div>

      {(["A", "B"] as const).map((g) => (
        <section key={g} className="risk-group">
          <h3>
            {t("riskGroup", { g })}
            <span className="muted">
              {" "}
              {g === "A" ? high?.a_count ?? 0 : high?.b_count ?? 0} / {master.high_impact.groups[g].length}
            </span>
          </h3>
          {master.high_impact.groups[g].map((row) => {
            const key = g === "A" ? "high_impact_a" : "high_impact_b";
            const on = input[key].includes(row.id);
            return (
              <label key={row.id} className={`risk-check ${on ? "on" : ""}`}>
                <input type="checkbox" checked={on} onChange={() => onToggle(key, row.id)} />
                <span className="risk-id">{row.id}</span>
                <span className="risk-text">{row.text}</span>
              </label>
            );
          })}
        </section>
      ))}

      <div className={`risk-verdict ${high?.high_impact ? "hi" : ""}`}>
        <strong>{high?.high_impact ? t("riskHighYes") : t("riskHighNo")}</strong>
        <span className="muted">{high?.reason}</span>
      </div>

      <section className="risk-group">
        <h3>{t("riskSafety")}</h3>
        <p className="risk-rule">
          {t("riskRule")}: <code>{master.safety.rule}</code>
          <span className="risk-src">{master.safety.source}</span>
        </p>
        {!high?.high_impact && <div className="banner note">{t("riskSafetySkipped")}</div>}
        <fieldset disabled={!high?.high_impact} className="risk-fieldset">
          {master.safety.items.map((row) => (
            <label
              key={row.id}
              className={`risk-check ${input.safety[row.id] ? "on" : ""}`}
            >
              <input
                type="checkbox"
                checked={!!input.safety[row.id]}
                onChange={(e) => onSafety(row.id, e.target.checked)}
              />
              <span className="risk-id">{row.id}</span>
              <span className="risk-text">{row.text}</span>
            </label>
          ))}
          <label className="risk-field">
            <span>{t("riskSafetyStage")}</span>
            <select value={input.safety_stage ?? ""} onChange={(e) => onStage(e.target.value)}>
              <option value="">—</option>
              {master.safety.stages.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
        {safety?.applicable && (
          <div className={`risk-verdict ${safety.safety_target ? "hi" : ""}`}>
            <strong>
              {safety.safety_target ? t("riskSafetyYes") : t("riskSafetyNo")}
            </strong>
            <span className="muted">{safety.reason}</span>
          </div>
        )}
      </section>
    </>
  );
}

// --------------------------------------------------------------------------
// STEP 2 — 평가세트 (서비스 프로파일 4축)
// --------------------------------------------------------------------------
function Step2({
  master,
  input,
  onProfile,
  onService,
}: {
  master: RiskMaster;
  input: RiskInput;
  onProfile: (key: string, value: string) => void;
  onService: (uuid: string, name: string) => void;
}) {
  const { t } = useLang();
  return (
    <>
      <h2>{t("riskStep2")}</h2>

      <section className="risk-group">
        <h3>{t("riskService")}</h3>
        <label className="risk-field">
          <span>{t("riskServiceId")}</span>
          <input
            value={input.service_uuid ?? ""}
            placeholder="svc-credit-scoring"
            onChange={(e) => onService(e.target.value, input.service_name ?? "")}
          />
        </label>
        <label className="risk-field">
          <span>{t("riskServiceName")}</span>
          <input
            value={input.service_name ?? ""}
            onChange={(e) => onService(input.service_uuid ?? "", e.target.value)}
          />
        </label>
      </section>

      {/* 원본에서 4축 → 항목 매핑을 확정하지 못했다. 추측으로 필터를 만들면
          근거 없는 제외가 되므로, 안내라는 것을 화면에 명시한다. */}
      <div className="banner note">{master.evaluation_set.note}</div>

      {master.profile_axes.map((axis) => (
        <section key={axis.key} className="risk-group">
          <h3>{axis.label}</h3>
          <div className="risk-choices">
            {axis.options.map((opt) => (
              <label
                key={opt}
                className={`risk-choice ${input.profile[axis.key] === opt ? "on" : ""}`}
              >
                <input
                  type="radio"
                  name={axis.key}
                  checked={input.profile[axis.key] === opt}
                  onChange={() => onProfile(axis.key, opt)}
                />
                {opt}
              </label>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

// --------------------------------------------------------------------------
// STEP 3 — 위험 식별 · STEP 4 — 완화
// --------------------------------------------------------------------------
function ItemTable({
  master,
  input,
  result,
  onItem,
  mode,
}: {
  master: RiskMaster;
  input: RiskInput;
  result: RiskResult | null;
  onItem: (no: number, next: Partial<RiskItemInput>) => void;
  mode: "identify" | "mitigate";
}) {
  const { t } = useLang();
  const [lv1, setLv1] = useState<string>("");
  // 조언은 항목 하나씩 연다. 32개를 한꺼번에 물으면 사내 GPU 가 오래 잡힌다.
  const [asking, setAsking] = useState<number | null>(null);
  const [advisors, setAdvisors] = useState<RiskAdvisor[]>([]);
  const [allowExternal, setAllowExternal] = useState(false);

  useEffect(() => {
    api.reg.risk
      .advisors()
      .then((r) => setAdvisors(r.advisors))
      .catch(() => undefined);
  }, []);
  const groups = useMemo(
    () => Array.from(new Set(master.items.map((i) => i.lv1))),
    [master]
  );
  const rows = useMemo(
    () =>
      master.items.filter(
        (i) =>
          (!lv1 || i.lv1 === lv1) &&
          (mode === "identify" || itemOf(input, i.no).identified)
      ),
    [master, lv1, mode, input]
  );
  const scored = new Map((result?.rows ?? []).map((r) => [r.no, r]));

  return (
    <>
      <div className="risk-filter">
        <button className={`chip ${lv1 === "" ? "on" : ""}`} onClick={() => setLv1("")}>
          {t("riskAll")} ({master.items.length})
        </button>
        {groups.map((g) => (
          <button
            key={g}
            className={`chip ${lv1 === g ? "on" : ""}`}
            onClick={() => setLv1(g)}
          >
            {g} ({master.items.filter((i) => i.lv1 === g).length})
          </button>
        ))}
      </div>

      {mode === "mitigate" && rows.length === 0 && (
        <div className="banner note">{t("riskNothingIdentified")}</div>
      )}

      <div className="risk-table-wrap">
        <table className="risk-table">
          <thead>
            <tr>
              <th>No</th>
              <th>{t("riskCol1")}</th>
              <th>{t("riskCol2")}</th>
              <th className="num">{t("riskPoints")}</th>
              {mode === "identify" ? (
                <th>{t("riskIdentified")}</th>
              ) : (
                <>
                  <th>{t("riskMitigated")}</th>
                  <th>{t("riskResidual")}</th>
                  <th className="num">{t("riskWeight")}</th>
                </>
              )}
              <th className="num">{t("riskScore")}</th>
              <th>{t("riskAdvice")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((spec) => {
              const cur = itemOf(input, spec.no);
              const out = scored.get(spec.no);
              return (
                <Fragment key={spec.no}>
                <tr className={cur.identified ? "on" : ""}>
                  <td className="num">{spec.no}</td>
                  <td>
                    <div className="risk-lv3">{spec.lv3}</div>
                    <div className="muted small">
                      {spec.lv1} · {spec.lv2} · {spec.owner}
                    </div>
                  </td>
                  <td className="muted small">{spec.lv2}</td>
                  <td className="num">{spec.points}</td>
                  {mode === "identify" ? (
                    <td>
                      <label className="risk-toggle">
                        <input
                          type="checkbox"
                          checked={cur.identified}
                          onChange={(e) => onItem(spec.no, { identified: e.target.checked })}
                        />
                        <span>{cur.identified ? "Yes" : "No"}</span>
                      </label>
                    </td>
                  ) : (
                    <>
                      <td>
                        <label className="risk-toggle">
                          <input
                            type="checkbox"
                            checked={cur.mitigated}
                            onChange={(e) => onItem(spec.no, { mitigated: e.target.checked })}
                          />
                          <span>{cur.mitigated ? "Yes" : "No"}</span>
                        </label>
                      </td>
                      <td>
                        <div className="risk-residual">
                          {RESIDUAL_CODES.map((code) => (
                            <button
                              key={code}
                              className={`chip ${cur.residual === code ? "on" : ""}`}
                              disabled={!cur.mitigated}
                              title={
                                master.mitigation_weights.find((w) => w.code === code)?.label
                              }
                              onClick={() => onItem(spec.no, { residual: code })}
                            >
                              {code}
                            </button>
                          ))}
                        </div>
                      </td>
                      <td className="num">{fmt(out?.weight, 1)}</td>
                    </>
                  )}
                  <td className="num strong">{fmt(out?.residual_score, 1)}</td>
                  <td>
                    <button
                      className={`sb-mini ${asking === spec.no ? "on" : ""}`}
                      onClick={() => setAsking(asking === spec.no ? null : spec.no)}
                      title={t("riskAdviceNotVerdict")}
                    >
                      {asking === spec.no ? "✕" : t("riskAsk")}
                    </button>
                  </td>
                </tr>
                {asking === spec.no && (
                  <tr className="advice-row">
                    <td colSpan={mode === "identify" ? 7 : 9}>
                      <AdvicePanel
                        itemNo={spec.no}
                        stage={mode}
                        input={input}
                        advisors={advisors}
                        allowExternal={allowExternal}
                        onAllowExternal={setAllowExternal}
                        onClose={() => setAsking(null)}
                      />
                    </td>
                  </tr>
                )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}


// --------------------------------------------------------------------------
// sLM 조언 — 판정이 아니라 "판단 전에 무엇을 볼지"
//
// 모델은 Yes/No 를 내지 않는다. 응답 스키마에 판정 자리가 아예 없다.
// 사내 모델을 먼저 쓰고, 외부로 넘기는 것은 사용자가 켰을 때만 한다 —
// 프롬프트에 운영 소스의 테이블명·URL 이 들어가기 때문이다.
// --------------------------------------------------------------------------
const RELEVANCE_CLASS: Record<string, string> = {
  high: "rel-high",
  medium: "rel-med",
  low: "rel-low",
  unclear: "rel-unclear",
};

function AdvicePanel({
  itemNo,
  stage,
  input,
  advisors,
  allowExternal,
  onAllowExternal,
  onClose,
}: {
  itemNo: number;
  stage: "identify" | "mitigate";
  input: RiskInput;
  advisors: RiskAdvisor[];
  allowExternal: boolean;
  onAllowExternal: (v: boolean) => void;
  onClose: () => void;
}) {
  const { t } = useLang();
  const [advice, setAdvice] = useState<RiskAdvice | null>(null);
  const [busy, setBusy] = useState(false);

  const localReady = advisors.some((a) => a.local && a.ready.ok);
  const externalReady = advisors.some((a) => !a.local && a.ready.ok);

  const ask = useCallback(async () => {
    setBusy(true);
    setAdvice(null);
    try {
      const r = await api.reg.risk.advise({
        item_no: itemNo,
        stage,
        service: input.service_name || input.service_uuid || "",
        profile: input.profile,
        program_ids: [],
        note: itemOf(input, itemNo).note ?? "",
        allow_external: allowExternal,
      });
      setAdvice(r);
    } catch (e) {
      setAdvice({
        item_no: itemNo, stage, relevance: "unclear", summary: "",
        checkpoints: [], evidence: [], mitigations: [],
        provider: "", model: "", local: true, fell_back: false, tried: [],
        error: (e as Error).message, derivation: "llm", facts: {},
      });
    } finally {
      setBusy(false);
    }
  }, [itemNo, stage, input, allowExternal]);

  useEffect(() => {
    ask();
  }, [ask]);

  return (
    <div className="advice">
      <div className="advice-head">
        <strong>{t("riskAdviceTitle")}</strong>
        <span className="advice-note">{t("riskAdviceNotVerdict")}</span>
        <button className="sb-mini" onClick={onClose}>✕</button>
      </div>

      <div className="advice-providers">
        {advisors.map((a) => (
          <span key={a.id} className={`chip ${a.ready.ok ? "" : "off"}`} title={a.model}>
            {a.local ? t("riskAdvisorLocal") : t("riskAdvisorExternal")} · {a.id}
            {a.ready.ok ? "" : ` — ${t("providerUnavailable")}`}
          </span>
        ))}
        {/* 외부 허용은 기본이 꺼짐이다. 켜는 순간 프롬프트가 조직 밖으로 나간다. */}
        <label className="advice-external">
          <input
            type="checkbox"
            checked={allowExternal}
            onChange={(e) => onAllowExternal(e.target.checked)}
          />
          <span>{t("riskAllowExternal")}</span>
        </label>
      </div>

      {!localReady && !allowExternal && (
        <div className="banner warn">{t("riskNoLocalAdvisor")}</div>
      )}
      {allowExternal && externalReady && (
        <div className="banner warn">{t("riskExternalWarning")}</div>
      )}

      {busy && <div className="muted pad">{t("riskAsking")}</div>}

      {advice && !busy && (
        <>
          {advice.error ? (
            <div className="banner error">
              {advice.error}
              {advice.tried.length > 0 && (
                <ul>
                  {advice.tried.map((tr) => (
                    <li key={tr.provider}>
                      {tr.provider}: {tr.error}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <>
              <div className="advice-by">
                <span className={`chip ${advice.local ? "ok" : "warn"}`}>
                  {advice.local ? t("riskAdvisorLocal") : t("riskAdvisorExternal")} ·{" "}
                  {advice.provider} · {advice.model}
                </span>
                <span className={`chip ${RELEVANCE_CLASS[advice.relevance]}`}>
                  {t("riskRelevance")}: {t(`riskRel_${advice.relevance}` as never) || advice.relevance}
                </span>
                {advice.fell_back && (
                  <span className="chip warn">{t("riskFellBack")}</span>
                )}
              </div>

              {advice.summary && <p className="advice-summary">{advice.summary}</p>}

              {advice.checkpoints.length > 0 && (
                <>
                  <h4>{t("riskCheckpoints")}</h4>
                  <ul className="advice-list">
                    {advice.checkpoints.map((c) => <li key={c}>{c}</li>)}
                  </ul>
                </>
              )}
              {advice.evidence.length > 0 && (
                <>
                  <h4>{t("riskEvidenceHint")}</h4>
                  <ul className="advice-list">
                    {advice.evidence.map((c) => <li key={c}>{c}</li>)}
                  </ul>
                </>
              )}
              {advice.mitigations.length > 0 && (
                <>
                  <h4>{t("riskMitigationIdeas")}</h4>
                  <ul className="advice-list">
                    {advice.mitigations.map((c) => <li key={c}>{c}</li>)}
                  </ul>
                </>
              )}

              {(advice.facts.tables?.length || advice.facts.programs?.length) && (
                <div className="advice-facts">
                  <b>{t("riskCodeFacts")}</b>{" "}
                  {[...(advice.facts.programs ?? []), ...(advice.facts.tables ?? [])]
                    .slice(0, 12)
                    .join(" · ")}
                </div>
              )}

              <div className="advice-foot">
                {t("riskDecideYourself")}
                <button className="sb-mini" onClick={ask} disabled={busy}>
                  {t("riskAskAgain")}
                </button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function Step3(props: {
  master: RiskMaster;
  input: RiskInput;
  result: RiskResult | null;
  onItem: (no: number, next: Partial<RiskItemInput>) => void;
}) {
  const { t } = useLang();
  return (
    <>
      <h2>{t("riskStep3")}</h2>
      <p className="lede">{t("riskStep3Lede")}</p>
      <ItemTable {...props} mode="identify" />
    </>
  );
}

function Step4(props: {
  master: RiskMaster;
  input: RiskInput;
  result: RiskResult | null;
  onItem: (no: number, next: Partial<RiskItemInput>) => void;
}) {
  const { t } = useLang();
  return (
    <>
      <h2>{t("riskStep4")}</h2>
      <p className="lede">{t("riskStep4Lede")}</p>
      <div className="risk-legend">
        {props.master.mitigation_weights.map((w) => (
          <span key={w.code} className="risk-legend-item">
            <b>{w.code}</b> {w.weight.toFixed(1)} — {w.label}
          </span>
        ))}
        <span className="risk-legend-item warn">
          <b>No</b> {props.master.not_mitigated_weight.toFixed(1)} — {useLang().t("riskNoMitigation")}
        </span>
      </div>
      <ItemTable {...props} mode="mitigate" />
    </>
  );
}

// --------------------------------------------------------------------------
// STEP 5 — 등급 확정
// --------------------------------------------------------------------------
function Step5({ master, result }: { master: RiskMaster; result: RiskResult | null }) {
  const { t } = useLang();
  if (!result) return null;
  const final = result.final_grade;
  const d = master.rounding.display_decimals;

  return (
    <>
      <h2>{t("riskStep5")}</h2>

      <div className={`risk-grade g-${final.key}`}>
        <div className="risk-grade-label">{final.label}</div>
        <div className="risk-grade-score">
          {fmt(result.step4_residual_score, d)} / 100
        </div>
      </div>

      {final.override_applied && (
        <div className="banner warn">
          <strong>{t("riskOverride")}</strong>
          <div>
            {t("riskOverrideFrom", {
              from: result.computed_grade.label,
              to: final.label,
            })}
          </div>
          <div className="muted small">{final.override_source}</div>
        </div>
      )}

      <table className="risk-summary">
        <tbody>
          <tr>
            <th>{t("riskRecognized")}</th>
            <td className="num">{fmt(result.step3_recognized_score, d)}</td>
          </tr>
          <tr>
            <th>{t("riskResidualTotal")}</th>
            <td className="num strong">{fmt(result.step4_residual_score, d)}</td>
          </tr>
          <tr>
            <th>{t("riskComputedGrade")}</th>
            <td>{result.computed_grade.label}</td>
          </tr>
          <tr>
            <th>{t("riskHighImpact")}</th>
            <td>{result.step1_high_impact.high_impact ? "Yes" : "No"}</td>
          </tr>
          <tr>
            <th>{t("riskSafety")}</th>
            <td>
              {result.step1_safety.applicable
                ? result.step1_safety.safety_target
                  ? "Yes"
                  : "No"
                : t("riskNotApplicable")}
            </td>
          </tr>
        </tbody>
      </table>

      <h3>{t("riskByPrinciple")}</h3>
      <table className="risk-table">
        <thead>
          <tr>
            <th>{t("riskCol1")}</th>
            <th className="num">{t("riskCount")}</th>
            <th className="num">{t("riskPoints")}</th>
            <th className="num">{t("riskRecognized")}</th>
            <th className="num">{t("riskResidualTotal")}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(result.by_lv1).map(([lv1, v]) => (
            <tr key={lv1}>
              <td>{lv1}</td>
              <td className="num">{v.count}</td>
              <td className="num">{v.points}</td>
              <td className="num">{fmt(v.recognized, d)}</td>
              <td className="num strong">{fmt(v.residual, d)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>{t("riskBands")}</h3>
      <div className="risk-bands">
        {[...master.grades]
          .sort((a, b) => a.min - b.min)
          .map((g) => (
            <div key={g.key} className={`risk-band ${g.key === final.key ? "on" : ""}`}>
              <b>{g.label}</b>
              <span>
                {g.min}–{g.max}
              </span>
            </div>
          ))}
      </div>

      {/* 기술 임계값은 점수에 들어가지 않는다. 참고값이라는 것을 화면에서 못박는다. */}
      <h3>{t("riskThresholds")}</h3>
      <div className="banner note">{t("riskThresholdsNote")}</div>
      <table className="risk-table">
        <thead>
          <tr>
            <th>{t("riskItems")}</th>
            <th>{t("riskMetric")}</th>
            <th>{t("riskCriterion")}</th>
            <th>{t("riskSource")}</th>
          </tr>
        </thead>
        <tbody>
          {master.technical_thresholds.entries.map((e) => (
            <tr key={e.metric}>
              <td className="num">{e.items.join(", ")}</td>
              <td>{e.metric}</td>
              <td className="muted">{e.criterion}</td>
              <td className="muted small">{e.source}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="risk-versions-box">
        <strong>{t("riskBasis")}</strong>
        <ul>
          {Object.entries(result.versions).map(([k, v]) => (
            <li key={k}>
              {k}: {v}
            </li>
          ))}
        </ul>
        <div className="muted small">
          {t("riskAssessedAt", { at: result.assessed_at })} · derivation={result.derivation}
        </div>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------
// 우측 패널
// --------------------------------------------------------------------------
function ScorePanel({
  result,
  decimals,
}: {
  result: RiskResult | null;
  decimals: number;
}) {
  const { t } = useLang();
  if (!result) return null;
  const final = result.final_grade;
  return (
    <div className={`risk-score-panel g-${final.key}`}>
      <div className="risk-score-grade">{final.label}</div>
      <div className="risk-score-num">{fmt(result.step4_residual_score, decimals)}</div>
      <div className="risk-score-sub">
        {t("riskRecognized")} {fmt(result.step3_recognized_score, decimals)}
      </div>
      {final.override_applied && (
        <div className="risk-score-badge">{t("riskOverrideShort")}</div>
      )}
      <div className="risk-score-sub">
        {t("riskHighImpact")}: {result.step1_high_impact.high_impact ? "Yes" : "No"}
      </div>
    </div>
  );
}

function DraftList({
  drafts,
  onLoad,
  onDrop,
}: {
  drafts: RiskDraftRow[];
  onLoad: (uuid: string) => void;
  onDrop: (uuid: string) => void;
}) {
  const { t } = useLang();
  if (drafts.length === 0) return null;
  return (
    <div className="risk-drafts">
      <div className="risk-drafts-head">{t("riskSaved")}</div>
      {drafts.map((d) => (
        <div key={d.service_uuid} className="risk-draft">
          <button className="risk-draft-pick" onClick={() => onLoad(d.service_uuid)}>
            <span className="risk-draft-name">{d.service_name || d.service_uuid}</span>
            <span className="muted small">
              {d.grade} · {fmt(d.residual_score, 1)} · {d.saved_by}
            </span>
          </button>
          <button className="sb-mini" onClick={() => onDrop(d.service_uuid)}>
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
