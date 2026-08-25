/** 시계열 분석 — 같은 설비가 해가 바뀌며 어떤 값을 보였는가.
 *
 * 회의에서 나온 "무슨 보일러인데 몇 년도 것" 만으로 대략이 잡히게 하려는 화면이다.
 * 축은 **연도**이고 원본은 위키다. 위키가 비어 있으면 지어내지 않고, 대신 지식
 * 데이터베이스에 문서가 얼마나 들어와 있는지를 보여 다음 할 일이 보이게 한다.
 */
import { useEffect, useState } from "react";
import { api, type KbSector, type Timeseries } from "./api";
import { useLang } from "./i18n";

const TYPES = ["", "measure", "entity", "metric", "source", "concept", "regulation"];

export default function TimelineView({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { t } = useLang();
  const [sectors, setSectors] = useState<KbSector[]>([]);
  const [sector, setSector] = useState("");
  const [type, setType] = useState("");
  const [data, setData] = useState<Timeseries | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.kb.sectors().then((r) => setSectors(r.sectors)).catch(() => setSectors([]));
  }, []);

  useEffect(() => {
    setBusy(true);
    api.audit
      .timeseries(sector, type)
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e) => setErr((e as Error).message))
      .finally(() => setBusy(false));
  }, [sector, type]);

  const peak = Math.max(1, ...(data?.by_year ?? []).map((y) => y.pages));
  const ledgerPeak = Math.max(1, ...(data?.ledger_by_year ?? []).map((y) => y.documents));
  const empty = !busy && data && data.by_year.length === 0;

  return (
    <div className="page timeline">
      <h1>{t("tlTitle")}</h1>
      <p className="lede">{t("tlLede")}</p>

      {err && <div className="banner error">{err}</div>}

      <div className="tl-filters">
        <label>
          <span>{t("tlSector")}</span>
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="">{t("tlAllSectors")}</option>
            {sectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("tlType")}</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((x) => (
              <option key={x} value={x}>
                {x || t("tlAllTypes")}
              </option>
            ))}
          </select>
        </label>
      </div>

      {empty && (
        <div className="banner warn tl-empty">
          <div>
            <strong>{t("tlEmpty")}</strong>
            <p className="muted small">{t("tlEmptyDesc")}</p>
          </div>
          <button className="primary" onClick={() => onNavigate("/admin")}>
            {t("tlGoAdmin")}
          </button>
        </div>
      )}

      {data && data.by_year.length > 0 && (
        <section>
          <h3>{t("tlByYear")}</h3>
          <div className="tl-bars">
            {data.by_year.map((y) => (
              <div key={y.year} className="tl-bar-row">
                <span className="tl-year">{y.year}</span>
                <div className="tl-track">
                  <i className="tl-fill" style={{ width: `${(y.pages / peak) * 100}%` }} />
                  <i
                    className="tl-fill verified"
                    style={{ width: `${(y.verified / peak) * 100}%` }}
                    title={t("tlVerified", { n: y.verified })}
                  />
                </div>
                <span className="tl-num">
                  {y.pages}
                  <em>{t("tlVerifiedShort", { n: y.verified })}</em>
                </span>
              </div>
            ))}
          </div>
          {data.undated > 0 && (
            <p className="muted small">{t("tlUndated", { n: data.undated })}</p>
          )}
        </section>
      )}

      {data && data.ledger_by_year.length > 0 && (
        <section>
          <h3>{t("tlLedger")}</h3>
          <p className="muted small">{t("tlLedgerDesc")}</p>
          <div className="tl-bars">
            {data.ledger_by_year.map((y) => (
              <div key={y.year} className="tl-bar-row">
                <span className="tl-year">{y.year}</span>
                <div className="tl-track">
                  <i
                    className="tl-fill ledger"
                    style={{ width: `${(y.documents / ledgerPeak) * 100}%` }}
                  />
                </div>
                <span className="tl-num">{y.documents}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {data && data.rows.length > 0 && (
        <section>
          <h3>{t("tlRows", { n: data.rows.length })}</h3>
          <div className="table-scroll">
            <table className="tl-table">
              <thead>
                <tr>
                  <th>{t("tlColYear")}</th>
                  <th>{t("tlColTitle")}</th>
                  <th>{t("tlColType")}</th>
                  <th>{t("tlColSector")}</th>
                  <th>{t("tlColVerified")}</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.stable_id}>
                    <td>{r.year || "—"}</td>
                    <td>
                      <button className="linkish" onClick={() => onNavigate(`/wiki/browse`)}>
                        {r.title}
                      </button>
                    </td>
                    <td>{r.type}</td>
                    <td>{r.sector_name || "—"}</td>
                    <td>{r.numeric_verified ? "✓" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
