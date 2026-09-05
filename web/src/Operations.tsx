/** AI 운영 — 배포 후에 보는 자리.
 *
 * 이 역할에 메뉴가 하나뿐이었다. 회의가 말한 운영자의 일(정기 모니터링·결과
 * 보고·재평가 트리거)에 해당하는 화면이 없었기 때문이다. 그중 **데이터 점검**을
 * 먼저 낸다 — 설계와 운영 양쪽에서 지침이 요구하는 것이고, 룰로 잴 수 있다.
 *
 * 지키는 선은 다른 화면과 같다.
 *
 *   · **수치는 서버의 룰이 센다.** 결측률·집단 분포·집단 간 격차(DI). 같은
 *     파일이면 언제 돌려도 같은 값이다. LLM 은 이 계산에 개입하지 않는다.
 *   · **판정하지 않는다.** 임계치 밖이라는 사실만 말하고, 32항목의 Yes/No 는
 *     위험등급 산정 화면에서 사람이 누른다.
 *   · **임계치의 출처를 함께 낸다.** DI 0.8~1.25 는 RMF 규정이 아니라 미국
 *     EEOC 4/5 룰에서 온 관행값이다. 근거 없는 숫자로 사람을 움직이면 안 된다.
 *   · **올린 파일을 남기지 않는다.** 보존기간과 파기 절차가 정해지기 전까지는
 *     분석하고 지운다.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Assist from "./Assist";
import { api, type DataAnalysis } from "./api";
import { useLang } from "./i18n";

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export default function Operations({
  onNavigate,
}: {
  onNavigate: (path: string) => void;
}) {
  const { t } = useLang();
  const [result, setResult] = useState<DataAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const picker = useRef<HTMLInputElement>(null);

  // 소스 분석이 찾은 테이블. 데이터와 대조해 "어느 테이블에 자료가 없나" 를 낸다.
  // /api/tables 의 programs 는 프로그램 **이름 문자열** 배열이다 (객체가 아니다).
  type TableRow = { name: string; crud: string[]; programs: string[] };
  const [tables, setTables] = useState<TableRow[] | null>(null);
  const loadTables = useCallback(() => {
    api.tables().then(setTables).catch(() => setTables([]));
  }, []);
  useEffect(loadTables, [loadTables]);

  /** 업로드한 데이터셋이 어느 테이블과 이어졌나. 서버가 이름으로 맞춘 결과를 되짚는다. */
  const covered = useMemo(() => {
    const hit = new Set<string>();
    for (const ds of result?.datasets ?? []) {
      for (const l of ds.source_links ?? []) hit.add(l.table.toUpperCase());
    }
    return hit;
  }, [result]);

  const send = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    setBusy(true);
    setError("");
    api.reg
      .analyzeData(Array.from(list))
      .then(setResult)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <section className="ops">
      <header className="svc-head">
        <div>
          <h2>{t("opsTitle")}</h2>
          <p className="lede">{t("opsLede")}</p>
        </div>
      </header>

      <div className="ops-pick">
        {/* webkitdirectory — 폴더째 고른다. 브라우저가 상대경로를 함께 준다. */}
        <input
          ref={picker}
          type="file"
          multiple
          // @ts-expect-error 표준에 없지만 크롬·엣지·사파리가 지원한다
          webkitdirectory=""
          directory=""
          style={{ display: "none" }}
          onChange={(e) => send(e.target.files)}
        />
        <button className="btn" disabled={busy} onClick={() => picker.current?.click()}>
          {busy ? t("opsAnalyzing") : t("opsPickFolder")}
        </button>
        <span className="muted small">{t("opsPickHint")}</span>
      </div>

      {error && <div className="banner error">{error}</div>}

      {result && (
        <>
          <div className="banner note">
            {t("opsNotKept")}
            {result.datasets.some((d) => d.sampled) &&
              ` ${t("opsSampled").replace("{n}", String(result.max_rows))}`}
          </div>

          {/* ── 데이터셋 ─────────────────────────────────────────── */}
          <h3>{t("opsDatasets")}</h3>
          {result.datasets.length === 0 && <div className="muted pad">{t("opsNoData")}</div>}
          {result.datasets.map((ds) => (
            <article key={ds.path} className="ops-ds">
              <header>
                <b>{ds.name}</b>
                <span className="muted small">
                  {ds.error ? ds.error : t("opsRows").replace("{n}", ds.rows.toLocaleString())}
                </span>
                {/* 소스 분석과 이어지는 자리 — 이 데이터를 어느 프로그램이 쓰는가 */}
                {ds.source_links?.map((l) => (
                  <span key={l.table} className="chip s-ok" title={l.programs.map((p) => p.name).join(", ")}>
                    {l.table} · {l.programs.length}
                  </span>
                ))}
              </header>
              {ds.columns.length > 0 && (
                <div className="ops-cols">
                  <table className="reg-table">
                    <thead>
                      <tr>
                        <th>{t("opsCol")}</th>
                        <th>{t("opsKind")}</th>
                        <th className="num">{t("opsMissing")}</th>
                        <th className="num">{t("opsUnique")}</th>
                        <th>{t("opsTop")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ds.columns.map((c) => (
                        <tr key={c.name} className={c.missing_ratio >= 0.2 ? "on" : ""}>
                          <td>{c.name}</td>
                          <td className="muted small">{c.kind}</td>
                          <td className="num">{pct(c.missing_ratio)}</td>
                          <td className="num">{c.unique.toLocaleString()}</td>
                          <td className="muted small">
                            {c.top_value && `${c.top_value} (${pct(c.top_ratio)})`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </article>
          ))}

          {/* ── 편향성 ───────────────────────────────────────────── */}
          {result.bias.length > 0 && (
            <>
              <h3>{t("opsBias")}</h3>
              {result.bias.map((b, i) => (
                <article key={i} className={`ops-bias ${b.outside ? "out" : ""}`}>
                  <header>
                    <b>
                      {b.protected}
                      {b.protected_kind && <span className="muted small"> · {b.protected_kind}</span>}
                    </b>
                    <span className="muted small">→ {b.outcome} = {b.positive_value}</span>
                    <span className={`chip ${b.outside ? "s-pending" : "s-ok"}`}>
                      DI {b.di}
                    </span>
                  </header>
                  <table className="reg-table">
                    <thead>
                      <tr>
                        <th>{t("opsGroup")}</th>
                        <th className="num">n</th>
                        <th className="num">{t("opsRate")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {b.groups.map((g) => (
                        <tr key={g.value}>
                          <td>{g.value}</td>
                          <td className="num">{g.n.toLocaleString()}</td>
                          <td className="num">{pct(g.rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {/* 임계치의 출처를 반드시 함께 낸다 */}
                  <p className="muted small ops-src">
                    {b.criterion} · {t("opsSource").replace("{s}", b.source)}
                    {b.scored === false && ` · ${t("opsNotScored")}`}
                  </p>
                  {b.dropped_small_groups.length > 0 && (
                    <p className="muted small">
                      {t("opsDropped").replace("{g}", b.dropped_small_groups.join(", "))}
                    </p>
                  )}
                </article>
              ))}
            </>
          )}

          {/* ── 32항목 후보 ──────────────────────────────────────── */}
          {result.findings.length > 0 && (
            <>
              <h3>{t("opsFindings")}</h3>
              <p className="muted small">{t("opsFindingsNote")}</p>
              <ul className="ops-findings">
                {result.findings.map((f, i) => (
                  <li key={i}>
                    <span className="chip">{f.item_no}</span>
                    <span>
                      <b>{f.label}</b>
                      <div className="muted small">{f.because}</div>
                      <div className="muted small">{t("opsSource").replace("{s}", f.source)}</div>
                    </span>
                  </li>
                ))}
              </ul>
              <button className="btn ghost sm" onClick={() => onNavigate("/reg/risk")}>
                {t("opsGoRisk")}
              </button>
            </>
          )}
        </>
      )}

      {/* ── 소스 분석과 대조 ─────────────────────────────────────────
          코드가 만지는 테이블과 올린 데이터를 나란히 놓는다. 자료가 없는
          테이블은 '점검 안 된 곳' 이지 '문제 없는 곳' 이 아니다. */}
      {tables !== null && tables.length > 0 && (
        <>
          <h3>{t("opsCross")}</h3>
          <p className="muted small">{t("opsCrossNote")}</p>
          <div className="ops-cols">
            <table className="reg-table">
              <thead>
                <tr>
                  <th>{t("opsTable")}</th>
                  <th>{t("opsCrud")}</th>
                  <th>{t("opsPrograms")}</th>
                  <th>{t("opsHasData")}</th>
                </tr>
              </thead>
              <tbody>
                {tables.map((tb) => {
                  const has = covered.has(tb.name.toUpperCase());
                  return (
                    <tr key={tb.name} className={result && !has ? "on" : ""}>
                      <td>
                        <button className="linkish" onClick={() => onNavigate(`/t/${encodeURIComponent(tb.name)}`)}>
                          {tb.name}
                        </button>
                      </td>
                      <td className="muted small">{tb.crud.join(" ")}</td>
                      <td className="muted small">{tb.programs.join(", ")}</td>
                      <td>
                        {!result ? (
                          <span className="muted small">{t("opsNotChecked")}</span>
                        ) : has ? (
                          <span className="chip s-ok">{t("opsDataYes")}</span>
                        ) : (
                          <span className="chip s-pending">{t("opsDataNo")}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* 수치를 말로 풀어야 할 때. 계산은 이미 끝났고 모델은 설명만 한다. */}
      <Assist onNavigate={onNavigate} />
    </section>
  );
}
