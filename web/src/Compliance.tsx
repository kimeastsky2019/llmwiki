import { Fragment, useCallback, useEffect, useState } from "react";
import {
  api,
  type RegAssessResponse,
  type RegAssessment,
  type RegChange,
  type RegChangeDetail,
  type RegCoverage,
  type RegGoldset,
  type RegGrade,
  type RegGraph,
  type RegValidation,
} from "./api";
import { useLang } from "./i18n";
import RiskWizard from "./RiskWizard";

export type RegTab = "risk" | "assess" | "coverage" | "changes" | "graph";

export const REG_TABS: RegTab[] = ["risk", "assess", "coverage", "changes", "graph"];

/** 판정값 → CSS 클래스. 색은 화면에서만 쓰고 판정 자체는 서버가 정한다. */
const VERDICT_CLASS: Record<string, string> = {
  SATISFIED: "v-ok",
  PARTIAL: "v-partial",
  UNSATISFIED: "v-bad",
  DEFERRED: "v-defer",
  NOT_APPLICABLE: "v-na",
};

const STATUS_CLASS: Record<string, string> = {
  approved: "s-ok",
  pending_review: "s-pending",
  blocked: "s-blocked",
  rejected: "s-rejected",
};

/** 확정 서명자는 브라우저마다 다르다 — 매번 다시 입력하게 하지 않는다. */
const SIGNER_KEY = "llmwiki.reg.signer";

function readSigner(): string {
  try {
    return localStorage.getItem(SIGNER_KEY) ?? "gov-officer";
  } catch {
    return "gov-officer";
  }
}

export default function Compliance({
  tab,
  onTab,
}: {
  tab: RegTab;
  onTab: (t: RegTab) => void;
}) {
  const { t } = useLang();
  const [signer, setSignerState] = useState(readSigner);
  const [err, setErr] = useState<string | null>(null);
  const [triggerNotes, setTriggerNotes] = useState<Record<string, string>>({});
  // 승인·확정이 일어나면 올려서 모든 탭을 다시 읽게 한다
  const [refresh, setRefresh] = useState(0);

  const setSigner = useCallback((value: string) => {
    setSignerState(value);
    try {
      localStorage.setItem(SIGNER_KEY, value);
    } catch {
      /* 저장 못 해도 이번 세션에서는 동작한다 */
    }
  }, []);

  useEffect(() => {
    api.reg
      .schema()
      .then((s) => setTriggerNotes(s.deferral_triggers))
      .catch(() => undefined);
  }, []);

  const bumped = useCallback(() => setRefresh((n) => n + 1), []);

  return (
    <div className="page reg">
      <h1>{t("regTitle")}</h1>
      <p className="lede">{t("regLede")}</p>

      <div className="reg-tabs" role="tablist">
        {REG_TABS.map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            onClick={() => onTab(key)}
          >
            {t(
              key === "risk"
                ? "riskTabRisk"
                : key === "assess"
                  ? "regTabAssess"
                  : key === "coverage"
                    ? "regTabCoverage"
                    : key === "changes"
                      ? "regTabChanges"
                      : "regTabGraph"
            )}
          </button>
        ))}
      </div>

      {err && <div className="banner error">{err}</div>}

      {/* 위험등급 산정은 그래프가 아니라 32항목 배점으로 답한다 —
          같은 화면에 있지만 파이프라인이 다르다. */}
      {tab === "risk" && <RiskWizard key={`r${refresh}`} />}

      {tab === "assess" && (
        <AssessTab
          key={`a${refresh}`}
          signer={signer}
          onSigner={setSigner}
          triggerNotes={triggerNotes}
          onError={setErr}
          onChanged={bumped}
        />
      )}
      {tab === "coverage" && <CoverageTab key={`c${refresh}`} onError={setErr} />}
      {tab === "changes" && (
        <ChangesTab
          key={`h${refresh}`}
          signer={signer}
          onSigner={setSigner}
          onError={setErr}
          onChanged={bumped}
        />
      )}
      {tab === "graph" && <GraphTab key={`g${refresh}`} onError={setErr} />}
    </div>
  );
}

function SignerBox({
  signer,
  onSigner,
}: {
  signer: string;
  onSigner: (v: string) => void;
}) {
  const { t } = useLang();
  return (
    <label className="reg-signer" title={t("regSignerHint")}>
      <span>{t("regSigner")}</span>
      <input value={signer} onChange={(e) => onSigner(e.target.value)} />
    </label>
  );
}

// --------------------------------------------------------------------------
// 판정
// --------------------------------------------------------------------------
function AssessTab({
  signer,
  onSigner,
  triggerNotes,
  onError,
  onChanged,
}: {
  signer: string;
  onSigner: (v: string) => void;
  triggerNotes: Record<string, string>;
  onError: (e: string | null) => void;
  onChanged: () => void;
}) {
  const { t } = useLang();
  const [data, setData] = useState<RegAssessResponse | null>(null);
  const [gold, setGold] = useState<RegGoldset | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    onError(null);
    api.reg.assess().then(setData).catch((e) => onError(e.message));
    api.reg.goldset().then(setGold).catch(() => setGold(null));
  }, [onError]);

  const confirm = async (a: RegAssessment) => {
    setBusy(a.uuid);
    setNote(null);
    try {
      await api.reg.confirm(a.uuid, signer);
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const commit = async () => {
    setBusy("commit");
    try {
      const r = await api.reg.commit();
      setNote(t("regCommitted", { n: r.assessments }));
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!data) return <div className="muted">{t("loading")}</div>;
  if (data.assessments.length === 0)
    return (
      <div className="empty-state">
        <p className="empty-title">{t("regEmpty")}</p>
        <p className="muted">{t("regEmptyHint")}</p>
      </div>
    );

  const m = data.metrics;
  return (
    <>
      <div className="stats">
        <Stat label={t("regStatDecided")} value={`${m.decided}/${m.total}`} />
        <Stat label={t("regStatDeferred")} value={m.deferred} tone="defer" />
        <Stat label={t("regStatAuto")} value={`${Math.round(m.auto_rate * 100)}%`} />
        {gold && (
          <Stat
            label={t("regStatPrecision")}
            value={`${Math.round(gold.precision * 100)}%`}
            tone="ok"
          />
        )}
      </div>

      <div className="reg-actions">
        <SignerBox signer={signer} onSigner={onSigner} />
        <button className="btn" onClick={commit} disabled={busy === "commit"}>
          {t("regCommit")}
        </button>
      </div>
      {note && <div className="banner">{note}</div>}

      <div className="table-wrap">
        <table className="reg-table">
          <thead>
            <tr>
              <th>{t("regColService")}</th>
              <th>{t("regColControl")}</th>
              <th>{t("regColVerdict")}</th>
              <th>{t("regColRaw")}</th>
              <th>{t("regColBasis")}</th>
              <th>{t("regColSign")}</th>
            </tr>
          </thead>
          <tbody>
            {data.assessments.map((a) => {
              const expanded = open === a.uuid;
              return (
                // 목록의 바깥 요소가 Fragment 이므로 key 는 여기 있어야 한다
                <Fragment key={a.uuid}>
                  <tr
                    className={`reg-row ${expanded ? "open" : ""}`}
                    onClick={() => setOpen(expanded ? null : a.uuid)}
                  >
                    <td>{a.service_name || a.service_uuid}</td>
                    <td>
                      <code>{a.control_code}</code>
                      <div className="muted small">{a.control_title}</div>
                    </td>
                    <td>
                      <span className={`verdict ${VERDICT_CLASS[a.verdict] ?? ""}`}>
                        {a.label}
                      </span>
                    </td>
                    <td className="muted">
                      {data.verdict_labels[a.raw_verdict] ?? a.raw_verdict}
                    </td>
                    <td>
                      <div className="reg-reason">{a.reason}</div>
                      {a.triggers.length > 0 && (
                        <div className="trigger-row">
                          {a.triggers.map((code) => (
                            <span
                              key={code}
                              className="chip trigger"
                              title={triggerNotes[code] ?? code}
                            >
                              {code}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      {a.decision_status === "confirmed" ? (
                        <span className="chip signed">
                          {t("regConfirmed")} · {a.confirmed_by}
                        </span>
                      ) : (
                        <button
                          className="btn small"
                          disabled={busy === a.uuid || !signer.trim()}
                          onClick={(e) => {
                            e.stopPropagation();
                            confirm(a);
                          }}
                        >
                          {t("regConfirmBtn")}
                        </button>
                      )}
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="reg-detail-row">
                      <td colSpan={6}>
                        <div className="reg-detail">
                          <div>
                            <div className="reg-detail-label">
                              {t("regDetailEvidence")}
                            </div>
                            {a.evidence_ids.length === 0 ? (
                              <div className="muted">{t("regNoEvidence")}</div>
                            ) : (
                              <ul className="reg-list">
                                {a.evidence_ids.map((id) => (
                                  <li key={id}>
                                    <code>{id}</code>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                          <div>
                            <div className="reg-detail-label">
                              {t("regDetailVersions")}
                            </div>
                            <ul className="reg-list">
                              <li>ontology {a.versions.ontology}</li>
                              <li>ruleset {a.versions.ruleset}</li>
                              <li>standard {a.versions.standard || "—"}</li>
                              <li>
                                provisions{" "}
                                {a.versions.provisions
                                  .map((p) => p.number)
                                  .join(", ") || "—"}
                              </li>
                            </ul>
                          </div>
                        </div>
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
// 커버리지 갭
// --------------------------------------------------------------------------
function CoverageTab({ onError }: { onError: (e: string | null) => void }) {
  const { t } = useLang();
  const [data, setData] = useState<RegCoverage | null>(null);

  useEffect(() => {
    onError(null);
    api.reg.coverage().then(setData).catch((e) => onError(e.message));
  }, [onError]);

  if (!data) return <div className="muted">{t("loading")}</div>;

  return (
    <>
      <p className="lede">{t("regCoverageLede")}</p>
      <div className="stats">
        <Stat
          label={t("regUncovered")}
          value={data.summary.uncovered}
          tone={data.summary.uncovered ? "bad" : "ok"}
        />
        <Stat label={t("regPartial")} value={data.summary.partially_covered} />
        <Stat
          label={t("regManual")}
          value={data.summary.manual_controls}
          tone={data.summary.manual_controls ? "defer" : "ok"}
        />
      </div>

      <h2>{t("regUncovered")}</h2>
      {data.uncovered_obligations.length === 0 ? (
        <p className="muted">{t("regNoGap")}</p>
      ) : (
        <div className="table-wrap">
          <table className="reg-table">
            <thead>
              <tr>
                <th>{t("regColLevel")}</th>
                <th>{t("regColObligation")}</th>
                <th>{t("regColProvision")}</th>
              </tr>
            </thead>
            <tbody>
              {data.uncovered_obligations.map((row) => (
                <tr key={row.obligation}>
                  <td>
                    <span
                      className={`chip force-${row.level === "mandatory" ? "must" : "should"}`}
                    >
                      {row.level}
                    </span>
                  </td>
                  <td>{row.title}</td>
                  <td className="muted">{row.provisions.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>{t("regManual")}</h2>
      {data.manual_controls.length === 0 ? (
        <p className="muted">{t("regNoGap")}</p>
      ) : (
        <div className="cards">
          {data.manual_controls.map((row) => (
            <div key={row.control} className="card static">
              <div className="card-layer">{row.control}</div>
              <div className="card-title">{row.title}</div>
              <div className="muted small">{row.note}</div>
            </div>
          ))}
        </div>
      )}

      <h2>{t("regPartial")}</h2>
      {data.partially_covered.length === 0 ? (
        <p className="muted">{t("regNoGap")}</p>
      ) : (
        <div className="table-wrap">
          <table className="reg-table">
            <thead>
              <tr>
                <th>{t("regColObligation")}</th>
                <th>{t("regColControl")}</th>
                <th>{t("regColMapping")}</th>
              </tr>
            </thead>
            <tbody>
              {data.partially_covered.map((row, i) => (
                <tr key={`${row.obligation}-${i}`}>
                  <td>{row.title}</td>
                  <td>
                    <code>{row.control}</code>
                  </td>
                  <td>
                    <span className="chip">{row.mapping_type}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>{t("regNoEvidenceControls")}</h2>
      {data.controls_without_evidence.length === 0 ? (
        <p className="muted">{t("regNoGap")}</p>
      ) : (
        <div className="pill-row">
          {data.controls_without_evidence.map((row) => (
            <span key={row.control} className="pill" title={row.title}>
              {row.control}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
// 커밋 결재
// --------------------------------------------------------------------------
function ChangesTab({
  signer,
  onSigner,
  onError,
  onChanged,
}: {
  signer: string;
  onSigner: (v: string) => void;
  onError: (e: string | null) => void;
  onChanged: () => void;
}) {
  const { t } = useLang();
  const [rows, setRows] = useState<RegChange[] | null>(null);
  const [grades, setGrades] = useState<Record<string, RegGrade>>({});
  const [picked, setPicked] = useState<RegChangeDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    onError(null);
    api.reg
      .changes()
      .then((r) => {
        setRows(r.changes);
        setGrades(r.grades);
      })
      .catch((e) => onError(e.message));
  }, [onError]);

  const open = (id: string) => {
    setPicked(null);
    api.reg.change(id).then(setPicked).catch((e) => onError(e.message));
  };

  const act = async (kind: "approve" | "reject") => {
    if (!picked) return;
    setBusy(true);
    try {
      if (kind === "approve")
        await api.reg.approve(picked.changeset_id, signer, note);
      else await api.reg.reject(picked.changeset_id, signer, note);
      setNote("");
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!rows) return <div className="muted">{t("loading")}</div>;
  if (rows.length === 0) return <p className="muted">{t("regNoChanges")}</p>;

  return (
    <>
      <p className="lede">{t("regChangesLede")}</p>
      <div className="reg-actions">
        <SignerBox signer={signer} onSigner={onSigner} />
      </div>

      <div className="table-wrap">
        <table className="reg-table">
          <thead>
            <tr>
              <th>{t("regColId")}</th>
              <th>{t("regColGrade")}</th>
              <th>{t("regColStatus")}</th>
              <th>{t("regColProposer")}</th>
              <th>ops</th>
              <th>{t("regColImpact")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr
                key={c.changeset_id}
                className={`reg-row ${picked?.changeset_id === c.changeset_id ? "open" : ""}`}
                onClick={() => open(c.changeset_id)}
              >
                <td>
                  <code>{c.changeset_id}</code>
                </td>
                <td>
                  <span className={`chip grade ${c.impact?.breaking ? "breaking" : ""}`}>
                    {c.grade}
                  </span>
                </td>
                <td>
                  <span className={`status ${STATUS_CLASS[c.status] ?? ""}`}>
                    {c.status}
                  </span>
                </td>
                <td className="muted">{c.proposer?.id}</td>
                <td>{c.ops.length}</td>
                <td className="muted">
                  {c.impact?.affected_controls} / {c.impact?.affected_assessments} /{" "}
                  {c.impact?.affected_services}
                  {c.impact?.breaking && (
                    <span className="chip breaking-tag">{t("regBreaking")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {picked && (
        <div className="reg-panel">
          <h2>
            <code>{picked.changeset_id}</code>{" "}
            <span className={`status ${STATUS_CLASS[picked.status] ?? ""}`}>
              {picked.status}
            </span>
          </h2>
          <p className="muted">
            {t("regApprover")}: <strong>{picked.approver}</strong> ·{" "}
            {grades[picked.grade]?.scope}
          </p>
          <p className="muted">
            {t("regGateCheck")}: {picked.checks?.shacl ?? "—"}
          </p>

          {(picked.checks?.issues ?? []).length > 0 && (
            <div className="banner error">
              <strong>{t("regGateIssues")}</strong>
              <ul className="reg-list">
                {(picked.checks.issues ?? []).map((i, n) => (
                  <li key={n}>
                    <code>{i.code}</code> {i.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {picked.diff && (
            <div className="pill-row">
              <span className="pill url">
                {t("regDiffAdded")} {picked.diff.added_nodes.length} +{" "}
                {picked.diff.added_edges.length}
              </span>
              <span className="pill">
                {t("regDiffChanged")} {picked.diff.changed_nodes.length}
              </span>
              <span className="pill">
                {t("regDiffObsoleted")} {picked.diff.obsoleted.length}
              </span>
            </div>
          )}

          {picked.diff && picked.diff.added_nodes.length > 0 && (
            <ul className="reg-list diff">
              {picked.diff.added_nodes.slice(0, 12).map((n) => (
                <li key={n.id}>
                  <span className="diff-add">+</span> {n.type}{" "}
                  <code>{String(n.props.title ?? n.props.name ?? n.id)}</code>
                </li>
              ))}
            </ul>
          )}

          {picked.status === "pending_review" ? (
            <div className="reg-actions">
              <input
                className="reg-note"
                placeholder={t("regReviewNote")}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <button className="btn" disabled={busy || !signer.trim()} onClick={() => act("approve")}>
                {t("regApprove")}
              </button>
              <button
                className="btn ghost"
                disabled={busy || !signer.trim()}
                onClick={() => act("reject")}
              >
                {t("regReject")}
              </button>
            </div>
          ) : picked.status === "blocked" ? (
            <div className="banner warn">{t("regBlockedHint")}</div>
          ) : null}
        </div>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
// 그래프
// --------------------------------------------------------------------------
function GraphTab({ onError }: { onError: (e: string | null) => void }) {
  const { t } = useLang();
  const [graph, setGraph] = useState<RegGraph | null>(null);
  const [valid, setValid] = useState<RegValidation | null>(null);
  const [gold, setGold] = useState<RegGoldset | null>(null);

  useEffect(() => {
    onError(null);
    api.reg.graph().then(setGraph).catch((e) => onError(e.message));
    api.reg.validate().then(setValid).catch(() => setValid(null));
    api.reg.goldset().then(setGold).catch(() => setGold(null));
  }, [onError]);

  if (!graph) return <div className="muted">{t("loading")}</div>;

  return (
    <>
      <p className="lede">{t("regGraphLede")}</p>

      <div className="stats">
        <Stat label={t("regJournalSeq")} value={graph.seq} />
        <Stat label={t("regEdges")} value={graph.edges} />
        <Stat
          label={t("regPending")}
          value={graph.pending_changes}
          tone={graph.pending_changes ? "defer" : "ok"}
        />
      </div>

      {valid && (
        <div className={`banner ${valid.ok ? "" : "error"}`}>
          {valid.ok
            ? `✓ ${t("regValidateOk")}`
            : t("regValidateFail", { n: valid.errors })}
          {valid.issues.length > 0 && (
            <ul className="reg-list">
              {valid.issues.slice(0, 8).map((i, n) => (
                <li key={n}>
                  <code>{i.code}</code> {i.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <h2>{t("regNodeCounts")}</h2>
      <div className="pill-row">
        {Object.entries(graph.counts).map(([kind, n]) => (
          <span key={kind} className="pill">
            {kind} {n}
          </span>
        ))}
      </div>

      {gold && (
        <>
          <h2>{t("regGoldsetTitle")}</h2>
          <p className="lede">{t("regGoldsetLede")}</p>
          <div className="stats">
            <Stat
              label={t("regCoverageRate")}
              value={`${Math.round(gold.coverage * 100)}%`}
            />
            <Stat
              label={t("regPrecisionRate")}
              value={`${Math.round(gold.precision * 100)}%`}
              tone={gold.precision === 1 ? "ok" : "bad"}
            />
            <Stat label={t("regKappa")} value={gold.kappa.toFixed(3)} />
          </div>
          {gold.misses.map((m, n) => (
            <div key={n} className="banner error">
              {t("regGoldsetMiss")} — {m.service} / {m.control}: {m.expected} ≠ {m.actual}
            </div>
          ))}
        </>
      )}
    </>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value?: number | string;
  tone?: "ok" | "bad" | "defer";
}) {
  return (
    <div className={`stat ${tone ? `tone-${tone}` : ""}`}>
      <div className="stat-value">{value ?? "–"}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
