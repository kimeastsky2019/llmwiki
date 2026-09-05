/** 자가진단 — 담당자가 평가표를 채우는 자리.
 *
 * 관리자가 만든 표(`Sheets.tsx`)를 여기서 실제로 쓴다. 답은 32항목 **후보**로
 * 이어지고, 그 후보를 사람이 위험등급 산정 화면에서 확정한다.
 *
 * 화면이 지키는 것 둘.
 *
 *   · **답이 판정처럼 보이지 않게 한다.** 저장하면 후보가 나오지만 등급도
 *     점수도 나오지 않는다. 그 자리는 여기에 없다.
 *   · **어느 버전에 답하는지 보인다.** 표는 고쳐질 수 있어서, 나중에 "이 사람은
 *     무엇에 답한 것인가" 를 물으면 버전으로 답해야 한다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type RegSheet, type SheetQuestion, type SelfResponse } from "./api";
import { useLang } from "./i18n";

const SIGNER_KEY = "llmwiki.reg.signer";

function readSigner(): string {
  try {
    return localStorage.getItem(SIGNER_KEY) ?? "gov-officer";
  } catch {
    return "gov-officer";
  }
}

type Answers = Record<string, string | string[]>;

export default function SelfCheck({
  onNavigate,
}: {
  onNavigate: (path: string) => void;
}) {
  const { t } = useLang();
  const [sheets, setSheets] = useState<RegSheet[]>([]);
  const [services, setServices] = useState<{ uuid: string; name: string }[]>([]);
  const [done, setDone] = useState<SelfResponse[]>([]);
  const [sheetId, setSheetId] = useState("");
  const [service, setService] = useState("");
  const [answers, setAnswers] = useState<Answers>({});
  const [by, setBy] = useState(readSigner);
  const [saved, setSaved] = useState<SelfResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.reg
      .responses()
      .then((r) => {
        setSheets(r.sheets);
        setServices(r.services);
        setDone(r.responses);
        if (!sheetId && r.sheets.length) setSheetId(r.sheets[0].sheet_id);
        if (!service && r.services.length) setService(r.services[0].uuid);
      })
      .catch((e) => setError(String(e)));
  }, [sheetId, service]);
  useEffect(load, [load]);

  const sheet = useMemo(
    () => sheets.find((s) => s.sheet_id === sheetId) ?? null,
    [sheets, sheetId]
  );

  const set = (no: number, value: string | string[]) =>
    setAnswers((cur) => ({ ...cur, [String(no)]: value }));

  const submit = () => {
    if (!sheet) return;
    setBusy(true);
    setError("");
    setSaved(null);
    api.reg
      .saveResponse({ sheet_id: sheet.sheet_id, service_uuid: service, by, answers })
      .then((r) => {
        setSaved(r);
        try {
          localStorage.setItem(SIGNER_KEY, by);
        } catch { /* 저장 못 해도 답은 남았다 */ }
        load();
      })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <section className="sc">
      <header className="svc-head">
        <div>
          <h2>{t("scTitle")}</h2>
          <p className="lede">{t("scLede")}</p>
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}

      {sheets.length === 0 ? (
        <div className="banner note">{t("scNoSheet")}</div>
      ) : (
        <>
          <div className="sc-pick">
            <label>
              <span>{t("scSheet")}</span>
              <select value={sheetId} onChange={(e) => { setSheetId(e.target.value); setAnswers({}); setSaved(null); }}>
                {sheets.map((s) => (
                  <option key={s.sheet_id} value={s.sheet_id}>
                    {s.title} (v{s.version})
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{t("scService")}</span>
              <select value={service} onChange={(e) => { setService(e.target.value); setSaved(null); }}>
                {services.map((s) => (
                  <option key={s.uuid} value={s.uuid}>{s.name}</option>
                ))}
              </select>
            </label>
            <label>
              <span>{t("scAnsweredBy")}</span>
              <input value={by} onChange={(e) => setBy(e.target.value)} />
            </label>
          </div>

          {sheet && (
            <>
              <p className="muted small">
                {t("scVersionNote").replace("{v}", String(sheet.version))}
              </p>

              {sheet.questions.map((q) => (
                <Question key={q.no} q={q} value={answers[String(q.no)]} onChange={set} />
              ))}

              <div className="ctrl-submit">
                <button className="btn" disabled={busy || !service} onClick={submit}>
                  {busy ? "…" : t("scSubmit")}
                </button>
              </div>
              <p className="muted small">{t("scSubmitNote")}</p>
            </>
          )}

          {/* ── 저장 결과 — 후보만 나온다. 등급·점수 자리는 없다. ─────────── */}
          {saved && (
            <div className="sc-result">
              <div className="banner ok">
                <b>{t("scSaved")}</b>{" "}
                {t("scSavedAt")
                  .replace("{who}", saved.answered_by)
                  .replace("{at}", (saved.answered_at || "").slice(0, 16).replace("T", " "))}
              </div>
              {saved.candidates.length === 0 ? (
                <p className="muted small">{t("scNoCandidate")}</p>
              ) : (
                <>
                  <h3>{t("scCandidates")}</h3>
                  <p className="muted small">{t("scCandidatesNote")}</p>
                  <ul className="ops-findings">
                    {saved.candidates.map((c, i) => (
                      <li key={i}>
                        <span className="chip">{c.item_no}</span>
                        <span>
                          <b>{c.label}</b>
                          <div className="muted small">{c.because}</div>
                          <div className="muted small">{c.source}</div>
                        </span>
                      </li>
                    ))}
                  </ul>
                  <button className="btn ghost sm" onClick={() => onNavigate("/reg/risk")}>
                    {t("scGoRisk")}
                  </button>
                </>
              )}
            </div>
          )}

          {/* ── 이미 답한 것 ─────────────────────────────────────────── */}
          {done.length > 0 && (
            <>
              <h3>{t("scDone")}</h3>
              <ul className="task-list">
                {done.map((r, i) => (
                  <li key={i}>
                    <span className="chip">{r.sheet_title} v{r.sheet_version}</span>
                    <span className="task-name">{r.service_name}</span>
                    <span className="muted small">
                      {t("scDoneBy")
                        .replace("{who}", r.answered_by)
                        .replace("{n}", String(r.candidates.length))}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------
// 질문 하나
// --------------------------------------------------------------------------
function Question({
  q, value, onChange,
}: {
  q: SheetQuestion;
  value: string | string[] | undefined;
  onChange: (no: number, value: string | string[]) => void;
}) {
  const { t } = useLang();
  const picked = Array.isArray(value) ? value : [];

  return (
    <div className="sc-q">
      <div className="sc-q-head">
        <span className="sh-q-no">{q.no}</span>
        <div>
          <div className="sc-q-text">
            {q.text}
            {q.required && <span className="sc-req">*</span>}
          </div>
          {q.help && <div className="muted small">{q.help}</div>}
        </div>
      </div>

      <div className="sc-q-body">
        {q.kind === "yesno" && (
          <div className="sc-choices">
            {[["yes", t("scYes")], ["no", t("scNo")]].map(([v, label]) => (
              <label key={v}>
                <input type="radio" name={`q${q.no}`} checked={value === v}
                       onChange={() => onChange(q.no, v)} />
                <span>{label}</span>
              </label>
            ))}
          </div>
        )}

        {(q.kind === "single" || q.kind === "scale") && (
          <div className="sc-choices">
            {q.options.map((o) => (
              <label key={o}>
                <input type="radio" name={`q${q.no}`} checked={value === o}
                       onChange={() => onChange(q.no, o)} />
                <span>{o}</span>
              </label>
            ))}
          </div>
        )}

        {q.kind === "multi" && (
          <div className="sc-choices">
            {q.options.map((o) => (
              <label key={o}>
                <input
                  type="checkbox"
                  checked={picked.includes(o)}
                  onChange={(e) =>
                    onChange(q.no, e.target.checked
                      ? [...picked, o]
                      : picked.filter((x) => x !== o))
                  }
                />
                <span>{o}</span>
              </label>
            ))}
          </div>
        )}

        {q.kind === "text" && (
          <textarea
            rows={3}
            value={typeof value === "string" ? value : ""}
            onChange={(e) => onChange(q.no, e.target.value)}
            placeholder={t("scTextHint")}
          />
        )}
      </div>
    </div>
  );
}
