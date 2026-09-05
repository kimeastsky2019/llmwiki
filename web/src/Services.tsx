/** 서비스 축 — 코드 분석과 규제 검증이 붙는 자리.
 *
 * 지금까지 화면은 두 개의 독립된 제품이 한 사이드바를 공유하는 모양이었다.
 * 분석에서 나온 사실이 규제 쪽 입력으로 흘러가지 않았고, 두 그래프를 잇는
 * `link-programs` 는 CLI 에만 있어 사용자가 그 기능의 존재를 알 수 없었다.
 *
 * 여기가 그 다리다. 그리고 이 화면이 지키는 규칙이 하나 있다 —
 * **묶는 것은 사람이 하고, 무엇이 있는지는 기계가 말한다.** 프로그램 목록과
 * 그 프로그램이 만지는 테이블은 정적 분석이 확인한 사실이지만, 어디까지를 한
 * 서비스로 볼지는 업무 판단이라 자동으로 정하지 않는다. 제안조차 하지 않는다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type RegProgramCandidate,
  type RegServiceDetail,
  type RegServiceRow,
  type RegStage,
} from "./api";
import { useLang, type StringKey } from "./i18n";

const PROPOSER_KEY = "llmwiki.reg.signer";

function readProposer(): string {
  try {
    return localStorage.getItem(PROPOSER_KEY) ?? "gov-officer";
  } catch {
    return "gov-officer";
  }
}

const STAGE_LABEL: Record<RegStage, StringKey> = {
  define: "svcStageDefine",
  grade: "svcStageGrade",
  controls: "svcStageControls",
  assess: "svcStageAssess",
  confirm: "svcStageConfirm",
  done: "svcStageDone",
};

const STAGE_NEXT: Record<RegStage, StringKey> = {
  define: "svcNextDefine",
  grade: "svcNextGrade",
  controls: "svcNextControls",
  assess: "svcNextAssess",
  confirm: "svcNextConfirm",
  done: "svcNextDone",
};

const VERDICT_CLASS: Record<string, string> = {
  SATISFIED: "v-ok",
  PARTIAL: "v-partial",
  UNSATISFIED: "v-bad",
  DEFERRED: "v-defer",
  NOT_APPLICABLE: "v-na",
};

/** 진행바 — 서비스마다 따로 돈다. 서비스 A 가 ③ 이고 B 가 ⑥ 일 수 있다. */
function StageBar({ stage, stages }: { stage: RegStage; stages: RegStage[] }) {
  const { t } = useLang();
  const at = stages.indexOf(stage);
  return (
    <ol className="svc-stages" aria-label={t("svcStage")}>
      {stages
        .filter((s) => s !== "done")
        .map((s, i) => (
          <li
            key={s}
            className={i < at ? "past" : i === at ? "now" : ""}
            aria-current={i === at ? "step" : undefined}
          >
            <span className="svc-stage-dot" aria-hidden="true" />
            <span>{t(STAGE_LABEL[s])}</span>
          </li>
        ))}
    </ol>
  );
}

// --------------------------------------------------------------------------
// 목록 + 정의
// --------------------------------------------------------------------------
export default function Services({
  onOpen,
  onError,
}: {
  onOpen: (uuid: string) => void;
  onError: (e: string | null) => void;
}) {
  const { t } = useLang();
  const [rows, setRows] = useState<RegServiceRow[] | null>(null);
  const [stages, setStages] = useState<RegStage[]>([]);
  const [defining, setDefining] = useState(false);

  const load = useCallback(() => {
    api.reg
      .services()
      .then((r) => {
        setRows(r.services);
        setStages(r.stages);
      })
      .catch((e) => onError(e.message));
  }, [onError]);
  useEffect(load, [load]);

  return (
    <div className="svc">
      <header className="svc-head">
        <div>
          <h2>{t("svcTitle")}</h2>
          <p className="lede">{t("svcLede")}</p>
        </div>
        <button className="btn" onClick={() => setDefining((v) => !v)}>
          {defining ? t("svcCancel") : t("svcNew")}
        </button>
      </header>

      {defining && (
        <DefineService
          onError={onError}
          onDone={() => {
            setDefining(false);
            load();
          }}
        />
      )}

      {rows === null && <div className="muted">{t("loading")}</div>}
      {rows?.length === 0 && <div className="banner note">{t("svcNone")}</div>}

      <div className="svc-cards">
        {(rows ?? []).map((s) => (
          <article key={s.uuid} className="svc-card">
            <button className="svc-card-open" onClick={() => onOpen(s.uuid)}>
              <h3>{s.name}</h3>
              <div className="muted small mono">{s.uuid}</div>
            </button>
            <StageBar stage={s.stage} stages={stages} />
            <dl className="svc-stats">
              <div>
                <dt>{t("svcPrograms")}</dt>
                <dd>{s.programs}</dd>
              </div>
              <div>
                <dt>{t("svcGrade")}</dt>
                <dd>{s.grade?.label || <span className="muted">{t("svcNoGrade")}</span>}</dd>
              </div>
              <div>
                <dt>{t("svcControls")}</dt>
                <dd>{s.controls}</dd>
              </div>
              <div>
                <dt>{t("svcUnconfirmed")}</dt>
                <dd>{s.unconfirmed}</dd>
              </div>
            </dl>
            <p className="svc-next">
              <b>{t("svcNext")}</b> {t(STAGE_NEXT[s.stage], { n: s.unconfirmed })}
            </p>
          </article>
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// 정의 — 프로그램을 골라 하나의 서비스로 묶는다
// --------------------------------------------------------------------------
function DefineService({
  onDone,
  onError,
}: {
  onDone: () => void;
  onError: (e: string | null) => void;
}) {
  const { t } = useLang();
  const [programs, setPrograms] = useState<RegProgramCandidate[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [dept, setDept] = useState("");
  const [proposer, setProposer] = useState(readProposer);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ id: string; approver: string } | null>(null);

  useEffect(() => {
    api.reg
      .programs()
      .then((r) => setPrograms(r.programs))
      .catch((e) => onError(e.message));
  }, [onError]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return programs ?? [];
    return (programs ?? []).filter(
      (p) =>
        p.name.toLowerCase().includes(needle) ||
        p.id.toLowerCase().includes(needle) ||
        p.tables.some((tb) => tb.toLowerCase().includes(needle))
    );
  }, [programs, q]);

  const toggle = (id: string) =>
    setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));

  const submit = async () => {
    onError(null);
    if (!name.trim()) return onError(t("svcNeedName"));
    if (!picked.length) return onError(t("svcNeedProgram"));
    if (!proposer.trim()) return onError(t("svcNeedProposer"));
    setBusy(true);
    try {
      localStorage.setItem(PROPOSER_KEY, proposer);
      const res = await api.reg.proposeService({
        name: name.trim(),
        program_ids: picked,
        by: proposer.trim(),
        dept: dept.trim(),
      });
      setDone({ id: res.changeset.changeset_id, approver: res.approver });
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <section className="svc-define">
        <div className="banner ok">
          {t("svcSubmitted", { id: done.id, approver: done.approver })}
        </div>
        <button className="btn" onClick={onDone}>
          {t("close")}
        </button>
      </section>
    );
  }

  return (
    <section className="svc-define">
      <p className="lede">{t("svcNewLede")}</p>
      {/* 결재를 거친다는 사실을 누르기 전에 말한다 — 누른 뒤에 알리면 늦다. */}
      <div className="banner note">{t("svcApprovalNote")}</div>

      <div className="svc-form">
        <label className="risk-field">
          <span>{t("svcName")}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="risk-field">
          <span>{t("svcDept")}</span>
          <input value={dept} onChange={(e) => setDept(e.target.value)} />
        </label>
        <label className="risk-field">
          <span>{t("svcProposer")}</span>
          <input value={proposer} onChange={(e) => setProposer(e.target.value)} />
        </label>
      </div>

      <div className="svc-pick-head">
        <h3>
          {t("svcPickPrograms")} <span className="muted">{t("svcPicked", { n: picked.length })}</span>
        </h3>
        <input
          className="svc-search"
          placeholder={t("svcSearchPrograms")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {programs !== null && programs.length === 0 && (
        <div className="banner note">{t("svcNoPrograms")}</div>
      )}

      <ul className="svc-pick">
        {rows.map((p) => (
          <li key={p.id} className={picked.includes(p.id) ? "on" : ""}>
            <label>
              <input
                type="checkbox"
                checked={picked.includes(p.id)}
                onChange={() => toggle(p.id)}
              />
              <span className="svc-pick-name">{p.name}</span>
            </label>
            <div className="muted small">
              {p.layer} · {p.tables.slice(0, 4).join(", ") || "—"}
              {p.tables.length > 4 ? ` +${p.tables.length - 4}` : ""}
            </div>
            {p.services.length > 0 && (
              <div className="svc-taken">{t("svcAlready", { names: p.services.join(", ") })}</div>
            )}
          </li>
        ))}
      </ul>

      <button className="btn" onClick={submit} disabled={busy}>
        {t("svcSubmit")}
      </button>
    </section>
  );
}

// --------------------------------------------------------------------------
// 대시보드 — 이 서비스는 몇 등급이고, 무엇이 비어 있는가
// --------------------------------------------------------------------------
export function ServiceDashboard({
  uuid,
  onNavigate,
}: {
  uuid: string;
  onNavigate: (path: string) => void;
}) {
  const { t } = useLang();
  const [data, setData] = useState<RegServiceDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api.reg
      .service(uuid)
      .then(setData)
      .catch((e) => setErr(e.message));
  }, [uuid]);

  if (err) return <div className="page"><div className="banner error">{err}</div></div>;
  if (!data) return <div className="page muted">{t("loading")}</div>;

  const s = data.service;
  const manual = data.controls.filter((c) => c.manual_evidence > 0);

  return (
    <div className="page svc-dash">
      <button className="link-back" onClick={() => onNavigate("/reg/services")}>
        {t("svcBack")}
      </button>

      <header className="svc-dash-head">
        <div>
          <h1>{s.name}</h1>
          <p className="muted mono small">
            {s.uuid}
            {s.dept ? ` · ${s.dept}` : ""}
          </p>
        </div>
        {s.grade?.high_impact && <span className="sig high">{t("svcHighImpact")}</span>}
      </header>

      <StageBar stage={data.stage} stages={data.stages} />

      <div className="banner note svc-next-banner">
        <b>{t("svcNext")}</b> {t(STAGE_NEXT[data.stage], { n: s.unconfirmed })}
        {data.stage === "grade" && (
          <button className="btn ghost sm" onClick={() => onNavigate("/reg/risk")}>
            {t("svcGoRisk")}
          </button>
        )}
        {(data.stage === "assess" || data.stage === "confirm") && (
          <button className="btn ghost sm" onClick={() => onNavigate("/reg")}>
            {t("svcGoAssess")}
          </button>
        )}
      </div>

      {data.pending_changes.length > 0 && (
        <div className="banner warn">{t("svcPending", { n: data.pending_changes.length })}</div>
      )}

      <div className="svc-tiles">
        <Tile label={t("svcGrade")} value={data.grade?.label || t("svcNoGrade")} />
        <Tile label={t("svcScore")} value={data.grade?.residual_score ?? "—"} />
        <Tile label={t("svcPrograms")} value={s.programs} />
        <Tile label={t("svcControls")} value={s.controls} />
        <Tile label={t("svcManual")} value={s.manual_evidence} />
        <Tile label={t("svcUnconfirmed")} value={s.unconfirmed} />
      </div>

      <section>
        <h2>{t("svcFunctions")}</h2>
        <ul className="svc-fn">
          {data.functions.map((f) => (
            <li key={f.key}>
              <button className="linkish" onClick={() => onNavigate(`/p/${f.program_id}`)}>
                {f.name}
              </button>
              <span className="muted small mono"> {f.program_ref}</span>
              <span className="muted small"> · {t("svcEvidenceAuto", { n: f.evidences })}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>{t("svcControlsTitle")}</h2>
        {data.controls.length === 0 && <div className="muted">{t("svcNoControls")}</div>}
        {data.controls.length > 0 && (
          <table className="reg-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>{t("svcControlsTitle")}</th>
                <th className="num">{t("svcManual")}</th>
              </tr>
            </thead>
            <tbody>
              {data.controls.map((c) => (
                <tr key={c.code}>
                  <td className="mono">{c.code}</td>
                  <td>{c.title}</td>
                  <td className="num">
                    {c.manual_evidence}/{c.required_evidence}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {manual.length > 0 && <p className="muted small">{t("svcManualHint")}</p>}
      </section>

      <section>
        <h2>{t("svcAssessments")}</h2>
        {data.assessments.length === 0 && <div className="muted">{t("svcNoAssessments")}</div>}
        {data.assessments.length > 0 && (
          <table className="reg-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Verdict</th>
                <th>Status</th>
                <th>At</th>
              </tr>
            </thead>
            <tbody>
              {data.assessments.map((a) => (
                <tr key={a.uuid}>
                  <td className="mono">{a.control_code}</td>
                  <td>
                    <span className={`verdict ${VERDICT_CLASS[a.verdict] ?? ""}`}>
                      {a.verdict}
                    </span>
                  </td>
                  <td className="muted small">{a.decision_status}</td>
                  <td className="muted small mono">{a.assessed_at?.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="svc-tile">
      <div className="svc-tile-label">{label}</div>
      <div className="svc-tile-value">{value}</div>
    </div>
  );
}


// --------------------------------------------------------------------------
// 사이드바 — 규제 모드에서는 **서비스**가 탐색 단위다
//
// 소스 분석 모드의 프로그램 트리가 여기 그대로 남아 있으면, 규제 작업을 하는
// 사람이 프로그램 이름으로 길을 찾게 된다. 축이 다르면 사이드바도 달라야 한다.
// --------------------------------------------------------------------------
export function ServiceNav({
  activeUuid,
  onPick,
}: {
  activeUuid: string | null;
  onPick: (path: string) => void;
}) {
  const { t } = useLang();
  const [rows, setRows] = useState<RegServiceRow[] | null>(null);

  useEffect(() => {
    api.reg
      .services()
      .then((r) => setRows(r.services))
      .catch(() => setRows([]));
  }, []);

  if (!rows?.length) return null;

  return (
    <nav className="svc-nav" aria-label={t("svcTitle")}>
      <div className="svc-nav-title">{t("svcTitle")}</div>
      {rows.map((s) => (
        <button
          key={s.uuid}
          className={`svc-nav-item ${activeUuid === s.uuid ? "active" : ""}`}
          onClick={() => onPick(`/svc/${encodeURIComponent(s.uuid)}`)}
        >
          <span className="svc-nav-name">{s.name}</span>
          {/* 단계를 이름 옆에 둔다 — 메뉴를 '기능 목록'이 아니라 '어디까지 왔는가'로
              읽히게 하는 것이 이 사이드바의 목적이다. */}
          <span className="svc-nav-stage">{t(STAGE_LABEL[s.stage])}</span>
        </button>
      ))}
    </nav>
  );
}
