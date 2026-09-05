/** 기준 관리 — 관리자가 평가 항목과 지표를 만드는 자리.
 *
 * 목업의 '모니터링 지표' 표가 보여 주는 줄(지표 · 산식 · 근거 법규 · 임계치)을
 * 여기서 만든다. 저쪽이 운영 중 현재값을 보는 화면이라면 여기는 그 기준을
 * 정의하는 화면이다.
 *
 * 이 화면이 지키는 것이 둘 있다.
 *
 * 1. **만든다고 기준이 되지 않는다.** 저장 버튼이 없고 상신 버튼만 있다.
 *    통제 하나가 바뀌면 그 통제를 쓰는 모든 서비스의 판정이 바뀌므로, 기준을
 *    만드는 일이야말로 결재를 건너뛰면 안 된다. 눌러도 결재 큐에 올라갈 뿐이다.
 * 2. **임계치를 비워 두는 것을 막지 않는다.** 없는 것을 채우게 만들면 그 숫자가
 *    근거가 되어 버린다. 비면 판단 유보로 가고, 목록이 그 사실을 세어 보여 준다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type RegControl,
  type RegControlVocabulary,
  type RegProcedureInput,
} from "./api";
import { useLang } from "./i18n";

const PROPOSER_KEY = "llmwiki.reg.signer";

function readProposer(): string {
  try {
    return localStorage.getItem(PROPOSER_KEY) ?? "gov-officer";
  } catch {
    return "gov-officer";
  }
}

const EMPTY_METRIC: RegProcedureInput = {
  kind: "metric", metric: "", operator: "", threshold: "", unit: "",
};

/** 지표 한 줄을 사람이 읽는 문장으로. 임계치가 없으면 없다고 말한다. */
function metricLine(p: {
  metric: string; operator: string; threshold: number | null; unit: string;
}, undecided: string): string {
  if (!p.operator || p.threshold === null || p.threshold === undefined) {
    return `${p.metric} — ${undecided}`;
  }
  return `${p.metric} ${p.operator} ${p.threshold}${p.unit ?? ""}`;
}

export default function Controls() {
  const { t } = useLang();
  const [rows, setRows] = useState<RegControl[] | null>(null);
  const [vocab, setVocab] = useState<RegControlVocabulary | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    api.reg
      .controls()
      .then((r) => {
        setRows(r.controls);
        setVocab(r.vocabulary);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(load, [load]);

  const openThresholds = useMemo(
    () => (rows ?? []).reduce((n, c) => n + c.open_thresholds, 0),
    [rows]
  );

  return (
    <section className="ctrl-page">
      <header className="svc-head">
        <div>
          <h2>{t("ctrlTitle")}</h2>
          <p className="lede">{t("ctrlLede")}</p>
        </div>
        <button className="btn" onClick={() => setOpen((v) => !v)}>
          {open ? t("ctrlClose") : t("ctrlNew")}
        </button>
      </header>

      {error && <div className="banner error">{error}</div>}

      {open && vocab && (
        <ControlForm
          vocab={vocab}
          onDone={() => {
            setOpen(false);
            load();
          }}
        />
      )}

      {openThresholds > 0 && (
        <div className="banner note">
          {t("ctrlOpenThresholds").replace("{n}", String(openThresholds))}
        </div>
      )}

      <div className="ctrl-table-wrap">
        <table className="ctrl-table">
          <thead>
            <tr>
              <th>{t("ctrlCode")}</th>
              <th>{t("ctrlItem")}</th>
              <th>{t("ctrlMetric")}</th>
              <th>{t("ctrlBasis")}</th>
              <th>{t("ctrlOwner")}</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((c) => (
              <tr key={c.code}>
                <td className="mono">{c.code}</td>
                <td>
                  <div className="ctrl-name">{c.title}</div>
                  <div className="muted small">
                    {c.auto_level}
                    {c.category ? ` · ${c.category}` : ""}
                  </div>
                </td>
                <td>
                  {c.procedures.filter((p) => p.kind === "metric").length === 0 ? (
                    <span className="muted small">{t("ctrlNoMetric")}</span>
                  ) : (
                    <ul className="ctrl-metrics">
                      {c.procedures
                        .filter((p) => p.kind === "metric")
                        .map((p) => (
                          <li
                            key={p.seq}
                            className={p.operator ? "" : "undecided"}
                          >
                            <span className="mono">
                              {metricLine(p, t("ctrlThresholdUndecided"))}
                            </span>
                          </li>
                        ))}
                    </ul>
                  )}
                </td>
                <td className="ctrl-basis">
                  {c.obligations.length === 0 ? (
                    <span className="muted small">{t("ctrlNoBasis")}</span>
                  ) : (
                    c.obligations.map((o) => (
                      <div key={o.obligation} className="muted small">
                        {o.title}
                      </div>
                    ))
                  )}
                </td>
                <td className="muted small">{c.owner}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows !== null && rows.length === 0 && (
        <div className="banner note">{t("ctrlEmpty")}</div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------
// 정의 폼
// --------------------------------------------------------------------------
function ControlForm({
  vocab,
  onDone,
}: {
  vocab: RegControlVocabulary;
  onDone: () => void;
}) {
  const { t } = useLang();
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [autoLevel, setAutoLevel] = useState(vocab.auto_level[0] ?? "L1");
  const [category, setCategory] = useState("");
  const [owner, setOwner] = useState("");
  const [by, setBy] = useState(readProposer);
  const [procs, setProcs] = useState<RegProcedureInput[]>([{ ...EMPTY_METRIC }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{
    note: string;
    approver: string;
    rejected: { seq: number; reason: string }[];
  } | null>(null);

  const setProc = (i: number, next: Partial<RegProcedureInput>) =>
    setProcs((cur) => cur.map((p, j) => (j === i ? { ...p, ...next } : p)));

  const submit = () => {
    setBusy(true);
    setError("");
    api.reg
      .proposeControl({
        by,
        code,
        title,
        auto_level: autoLevel,
        category,
        owner,
        // 빈 줄은 보내지 않는다. 지표는 산식이 있어야 지표다.
        procedures: procs.filter((p) => p.kind !== "metric" || (p.metric ?? "").trim()),
      })
      .then((r) => {
        setResult({ note: r.note, approver: r.approver, rejected: r.rejected });
        try {
          localStorage.setItem(PROPOSER_KEY, by);
        } catch {
          /* 저장 못 해도 상신은 이미 됐다 */
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  if (result) {
    return (
      <div className="svc-define ctrl-form">
        <div className="banner ok">
          <b>{t("ctrlStaged")}</b> {result.note}
        </div>
        <p className="muted small">
          {t("ctrlApprover").replace("{who}", result.approver)}
        </p>
        {result.rejected.length > 0 && (
          <div className="banner note">
            <b>{t("ctrlRejected")}</b>
            <ul>
              {result.rejected.map((r) => (
                <li key={r.seq}>
                  #{r.seq} — {r.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
        <button className="btn" onClick={onDone}>
          {t("ctrlDone")}
        </button>
      </div>
    );
  }

  return (
    <div className="svc-define ctrl-form">
      <p className="muted small">{t("ctrlFormLede")}</p>
      {error && <div className="banner error">{error}</div>}

      <div className="ctrl-grid">
        <label>
          <span>{t("ctrlCode")}</span>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="MON-11" />
        </label>
        <label className="wide">
          <span>{t("ctrlItem")}</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("ctrlItemHint")}
          />
        </label>
        <label>
          <span>{t("ctrlAutoLevel")}</span>
          <select value={autoLevel} onChange={(e) => setAutoLevel(e.target.value)}>
            {vocab.auto_level.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("ctrlCategory")}</span>
          <input value={category} onChange={(e) => setCategory(e.target.value)} />
        </label>
        <label>
          <span>{t("ctrlOwner")}</span>
          <input value={owner} onChange={(e) => setOwner(e.target.value)} />
        </label>
      </div>

      <h3 className="ctrl-sub">{t("ctrlProcedures")}</h3>
      <p className="muted small">{t("ctrlThresholdNote")}</p>

      {procs.map((p, i) => (
        <div className="ctrl-proc" key={i}>
          <select value={p.kind} onChange={(e) => setProc(i, { kind: e.target.value })}>
            {vocab.procedure_kind.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          {p.kind === "metric" && (
            <>
              <input
                className="mono"
                value={p.metric ?? ""}
                onChange={(e) => setProc(i, { metric: e.target.value })}
                placeholder={t("ctrlMetricHint")}
              />
              <select
                value={p.operator ?? ""}
                onChange={(e) => setProc(i, { operator: e.target.value })}
              >
                <option value="">{t("ctrlOpNone")}</option>
                {vocab.operator.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              <input
                className="mono num"
                value={String(p.threshold ?? "")}
                onChange={(e) => setProc(i, { threshold: e.target.value })}
                placeholder={t("ctrlThreshold")}
              />
              <input
                className="mono unit"
                value={p.unit ?? ""}
                onChange={(e) => setProc(i, { unit: e.target.value })}
                placeholder={t("ctrlUnit")}
              />
            </>
          )}
          <button
            className="sb-mini"
            onClick={() => setProcs((cur) => cur.filter((_, j) => j !== i))}
            title={t("ctrlRemoveProc")}
          >
            ✕
          </button>
        </div>
      ))}
      <button className="btn ghost sm" onClick={() => setProcs((c) => [...c, { ...EMPTY_METRIC }])}>
        {t("ctrlAddProc")}
      </button>

      <div className="ctrl-submit">
        <label>
          <span>{t("ctrlProposer")}</span>
          <input value={by} onChange={(e) => setBy(e.target.value)} />
        </label>
        <button className="btn" disabled={busy || !code.trim() || !title.trim()} onClick={submit}>
          {busy ? "…" : t("ctrlSubmit")}
        </button>
      </div>
      <p className="muted small">{t("ctrlSubmitNote")}</p>
    </div>
  );
}
