import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type KbSector,
  type WikiBuildResult,
  type WikiCheck,
  type WikiFinding,
  type WikiHealth,
  type WikiJournalRow,
  type WikiLint,
  type WikiQueueItem,
  type WikiReanalysis,
  type WikiSuggestion,
} from "./api";
import { useLang, type StringKey } from "./i18n";
import WikiStatusBoard from "./WikiStatusBoard";
import { useLlmChoice } from "./llmChoice";
import { useFileDrop } from "./useFileDrop";

export type AdminTab = "upload" | "queue" | "lint" | "journal";

export const ADMIN_TABS: AdminTab[] = ["upload", "queue", "lint", "journal"];

const TAB_KEY: Record<AdminTab, StringKey> = {
  upload: "adminTabUpload",
  queue: "adminTabQueue",
  lint: "adminTabLint",
  journal: "adminTabJournal",
};

const SEVERITY_CLASS: Record<string, string> = {
  blocker: "v-bad",
  error: "v-partial",
  warning: "v-partial",
  info: "v-na",
};

const SEVERITY_KEY: Record<string, StringKey> = {
  blocker: "kbSevBlocker",
  error: "kbSevError",
  warning: "kbSevWarning",
  info: "kbSevInfo",
};

/** 검토자 서명은 브라우저마다 다르다 — 매번 다시 입력하게 하지 않는다. */
const REVIEWER_KEY = "llmwiki.wiki.reviewer";

function readReviewer(): string {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}

export default function WikiAdmin({
  tab,
  onTab,
}: {
  tab: AdminTab;
  onTab: (t: AdminTab) => void;
}) {
  const { t } = useLang();
  const [health, setHealth] = useState<WikiHealth | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reviewer, setReviewerState] = useState(readReviewer);
  // 저장·검토가 일어나면 올려서 상태·큐·저널을 다시 읽게 한다
  const [refresh, setRefresh] = useState(0);

  const setReviewer = useCallback((next: string) => {
    setReviewerState(next);
    try {
      localStorage.setItem(REVIEWER_KEY, next);
    } catch {
      /* 실패해도 세션 안에서는 동작한다 */
    }
  }, []);

  useEffect(() => {
    api.wiki.health().then(setHealth).catch((e) => setErr(e.message));
  }, [refresh]);

  return (
    <div className="page wiki-admin">
      <h1>{t("adminTitle")}</h1>
      <p className="lede">{t("adminLede")}</p>

      {/* AI기본법 제31조제1항 — 사전 고지. 결과가 있든 없든 상시 노출한다. */}
      <div className="banner warn kb-notice">
        {t("kbPriorNotice")} <span className="muted small">{t("kbPriorNoticeLaw")}</span>
      </div>

      {err && <div className="banner error">{err}</div>}

      {health && !health.parser_ready.ok && (
        <div className="banner error">
          <strong>{health.parser_ready.reason}</strong>
          <pre>{health.parser_ready.hint}</pre>
        </div>
      )}

      {/* 생성·검산·배포를 나란히 둔다. 하나로 합치면 '위키는 제대로 만들어졌는데
          원문 수치가 어긋난' 상태를 표현할 수 없다. */}
      <WikiStatusBoard onNavigate={(p) => onTab(p.split("/")[2] as AdminTab)} refreshKey={refresh} />

      {health && (
        <div className="admin-status">
          <span className="muted small">
            {t("adminContract")} v{health.contract} · {t("adminPipeline")}{" "}
            {health.pipeline_version}
          </span>
          <span className="muted small">
            {t("kbDestination")}: <strong>{health.destination.name}</strong>{" "}
            {health.destination.cross_border ? t("kbDestOverseas") : t("kbDestDomestic")}
          </span>
          {health.units.expiring.length > 0 && (
            <span className="chip s-pending">
              {t("adminUnitsExpiring", { n: health.units.expiring.length })}
            </span>
          )}
        </div>
      )}

      <label className="admin-signer">
        <span>{t("adminReviewer")}</span>
        <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        <span className="muted small">{t("adminReviewerHint")}</span>
      </label>

      <div className="tabs">
        {ADMIN_TABS.map((key) => (
          <button
            key={key}
            className={`tab ${tab === key ? "active" : ""}`}
            onClick={() => onTab(key)}
          >
            {t(TAB_KEY[key])}
          </button>
        ))}
      </div>

      {tab === "upload" && (
        <UploadTab
          owner={reviewer}
          accept={(health?.parser_ready.formats?.suffixes ?? [".pdf"]).join(",")}
          onError={setErr}
          onStored={() => setRefresh((n) => n + 1)}
        />
      )}
      {tab === "queue" && (
        <QueueTab
          reviewer={reviewer}
          refresh={refresh}
          onError={setErr}
          onDecided={() => setRefresh((n) => n + 1)}
        />
      )}
      {tab === "lint" && <LintTab refresh={refresh} onError={setErr} />}
      {tab === "journal" && <JournalTab refresh={refresh} onError={setErr} />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 업로드 — 미리보기는 저장하지 않는다
// --------------------------------------------------------------------------- //
function UploadTab({
  owner,
  accept,
  onError,
  onStored,
}: {
  owner: string;
  accept: string;
  onError: (m: string | null) => void;
  onStored: () => void;
}) {
  const { t } = useLang();
  const [file, setFile] = useState<File | null>(null);
  const [site, setSite] = useState("");
  const [sector, setSector] = useState("");
  const [sectors, setSectors] = useState<KbSector[]>([]);
  const [busy, setBusy] = useState<"" | "preview" | "ingest">("");
  const [result, setResult] = useState<WikiBuildResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.kb
      .sectors()
      .then((r) => setSectors(r.sectors))
      .catch(() => setSectors([]));
  }, []);

  const run = useCallback(
    async (mode: "preview" | "ingest") => {
      if (!file) return;
      setBusy(mode);
      onError(null);
      try {
        const fn = mode === "preview" ? api.wiki.preview : api.wiki.ingest;
        const res = await fn(file, site.trim(), sector || undefined, owner || undefined);
        setResult(res);
        if (mode === "ingest" && res.stored) onStored();
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setBusy("");
      }
    },
    [file, site, sector, owner, onError, onStored]
  );

  const { isOver, dropProps } = useFileDrop({
    accept,
    disabled: busy !== "",
    onFile: (f) => {
      setFile(f);
      setResult(null);
      onError(null);
    },
    onReject: (message) => {
      const [head, tail] = message.split(":");
      onError(
        /^\d+$/.test(head)
          ? t("kbDropMultiple", { n: head, name: tail })
          : t("kbDropReject", { got: message.split(" · ")[0], allowed: accept })
      );
    },
  });

  return (
    <div className="admin-upload">
      <div className="upload-row">
        <button
          className={`file-pick ${isOver ? "dropping" : ""}`}
          onClick={() => inputRef.current?.click()}
          {...dropProps}
        >
          <span>{isOver ? t("kbDropHere") : file ? file.name : t("kbPickFile")}</span>
          <span className="kb-drop-formats">{t("kbDropHint")}</span>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          hidden
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setResult(null);
          }}
        />

        <label>
          <span>{t("adminSiteKey")}</span>
          <input
            value={site}
            onChange={(e) => setSite(e.target.value)}
            placeholder="vitech"
          />
        </label>

        <label>
          <span>{t("kbSectorLabel")}</span>
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="">{t("kbSectorAuto")}</option>
            {sectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>

        <button
          className="primary"
          disabled={!file || busy !== ""}
          onClick={() => run("preview")}
        >
          {busy === "preview" ? t("adminPreviewing") : t("adminPreview")}
        </button>
        <button
          disabled={!file || busy !== ""}
          onClick={() => run("ingest")}
          title={t("kbIngestHint")}
        >
          {busy === "ingest" ? t("adminIngesting") : t("adminIngest")}
        </button>
      </div>

      <p className="muted small">{t("adminSiteKeyHint")}</p>
      <p className="muted small">{t("adminUploadNote")}</p>

      {result && <BuildResultView result={result} />}
    </div>
  );
}

function BuildResultView({ result }: { result: WikiBuildResult }) {
  const { t } = useLang();
  const failed = result.checks_failed;

  return (
    <div className="build-result">
      {!result.gate_allowed ? (
        <div className="banner error">
          <strong>{t("adminGateBlocked")}</strong>
        </div>
      ) : result.stored ? (
        <div className="banner ok">
          <strong>
            {t("adminStored", {
              pages: result.summary.pages,
              site: result.summary.site_key,
              period: result.summary.period,
            })}
          </strong>
        </div>
      ) : (
        <div className="banner warn">{t("adminNotStored")}</div>
      )}

      {result.warnings.map((w, i) => (
        <p key={i} className="muted small">
          ! {w}
        </p>
      ))}

      <section>
        <h3>{t("adminChecks")}</h3>
        <p className={failed.length ? "banner warn" : "banner ok"}>
          {t("adminChecksSummary", {
            total: result.checks.length,
            failed: failed.length,
          })}
        </p>
        <p className="muted small">{t("adminChecksNote")}</p>
        {failed.length > 0 && <CheckTable checks={failed} />}
      </section>

      <section>
        <h3>{t("adminGeneratedPages")}</h3>
        <table className="grid">
          <thead>
            <tr>
              <th>{t("adminColType")}</th>
              <th>{t("adminColPage")}</th>
              <th>{t("adminColAcl")}</th>
              <th>{t("adminColVerified")}</th>
            </tr>
          </thead>
          <tbody>
            {result.pages.map((p) => (
              <tr key={p.stable_id}>
                <td>{p.type}</td>
                <td>
                  <code className="inline-code">{p.stable_id}</code> {p.title}
                </td>
                <td>
                  <span className="chip acl">{p.acl}</span>
                </td>
                <td>
                  <span className={`chip ${p.numeric_verified ? "s-ok" : "s-blocked"}`}>
                    {p.numeric_verified ? t("wikiVerified") : t("wikiUnverified")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function CheckTable({ checks }: { checks: WikiCheck[] }) {
  const { t } = useLang();
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>{t("adminColCheck")}</th>
          <th>{t("adminColStated")}</th>
          <th>{t("adminColComputed")}</th>
          <th>{t("adminColFormula")}</th>
          <th>{t("adminColSource")}</th>
        </tr>
      </thead>
      <tbody>
        {checks.map((c, i) => (
          <tr key={i}>
            <td>{c.label}</td>
            <td className="num">{c.stated?.toLocaleString() ?? "—"}</td>
            <td className="num">{c.computed.toLocaleString()}</td>
            <td className="muted small">{c.formula}</td>
            <td className="muted small">{c.source}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// --------------------------------------------------------------------------- //
// 검증 큐
// --------------------------------------------------------------------------- //
function QueueTab({
  reviewer,
  refresh,
  onError,
  onDecided,
}: {
  reviewer: string;
  refresh: number;
  onError: (m: string | null) => void;
  onDecided: () => void;
}) {
  const { t } = useLang();
  const [items, setItems] = useState<WikiQueueItem[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [acks, setAcks] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.wiki
      .queue()
      .then((r) => setItems(r.queue))
      .catch((e) => onError(e.message));
  }, [refresh, onError]);

  const decide = useCallback(
    async (id: string, decision: "approve" | "reject" | "deprecate") => {
      setBusy(id);
      onError(null);
      try {
        await api.wiki.review(id, {
          decision,
          actor: reviewer,
          note: notes[id] ?? "",
          acknowledge_unverified: acks[id] ?? false,
        });
        onDecided();
        setItems((rows) => rows.filter((r) => r.stable_id !== id));
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setBusy("");
      }
    },
    [reviewer, notes, acks, onError, onDecided]
  );

  if (items.length === 0) {
    return <div className="muted pad">{t("adminQueueEmpty")}</div>;
  }

  return (
    <div className="admin-queue">
      <p className="muted small">{t("adminQueueNote")}</p>
      {items.map((item) => (
        <article key={item.stable_id} className="queue-card">
          <header>
            <span className="chip">{item.priority}</span>
            <strong>{item.title}</strong>
            <code className="inline-code">{item.stable_id}</code>
            <span className="chip acl">{item.acl}</span>
            <span className={`chip ${item.numeric_verified ? "s-ok" : "s-blocked"}`}>
              {item.numeric_verified ? t("wikiVerified") : t("wikiUnverified")}
            </span>
          </header>

          <p className="muted small">
            {t("adminColReason")}: {item.reasons.join(" · ")}
          </p>

          {item.blocking.length > 0 && (
            <div className="banner error">{t("adminBlockingNote")}</div>
          )}

          {item.findings.length > 0 && (
            <ul className="finding-list">
              {item.findings.slice(0, 4).map((f, i) => (
                <li key={i} className={`sev-${f.severity}`}>
                  <span className={`verdict ${SEVERITY_CLASS[f.severity] ?? ""}`}>
                    {t(SEVERITY_KEY[f.severity] ?? "kbSevInfo")}
                  </span>{" "}
                  <code className="inline-code">{f.code}</code> {f.message}
                </li>
              ))}
            </ul>
          )}

          <AssistPanel stableId={item.stable_id} reviewer={reviewer} onError={onError}
                       onApplied={onDecided} />

          <div className="queue-actions">
            <input
              placeholder={t("adminNote")}
              value={notes[item.stable_id] ?? ""}
              onChange={(e) =>
                setNotes((n) => ({ ...n, [item.stable_id]: e.target.value }))
              }
            />
            {!item.numeric_verified && (
              <label className="ack" title={t("adminAckHint")}>
                <input
                  type="checkbox"
                  checked={acks[item.stable_id] ?? false}
                  onChange={(e) =>
                    setAcks((a) => ({ ...a, [item.stable_id]: e.target.checked }))
                  }
                />
                <span>{t("adminAckUnverified")}</span>
              </label>
            )}
            <button
              className="primary"
              disabled={busy === item.stable_id || item.blocking.length > 0}
              onClick={() => decide(item.stable_id, "approve")}
            >
              {t("adminApprove")}
            </button>
            <button
              disabled={busy === item.stable_id}
              onClick={() => decide(item.stable_id, "reject")}
            >
              {t("adminReject")}
            </button>
            <button
              disabled={busy === item.stable_id}
              onClick={() => decide(item.stable_id, "deprecate")}
            >
              {t("adminDeprecate")}
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

/** 서술 초안 제안 — 이 화면에서 LLM 을 부르는 유일한 자리다.
 *  수치는 코드가 만들고(P2), 등급이 경로를 정한다(P5). 둘 다 서버가 집행하므로
 *  화면은 결정 결과와 검사 결과를 그대로 보여 주기만 한다. */
function AssistPanel({
  stableId,
  reviewer,
  onError,
  onApplied,
}: {
  stableId: string;
  reviewer: string;
  onError: (m: string | null) => void;
  onApplied: () => void;
}) {
  const { t } = useLang();
  // 공급자는 사이드바에서 솔루션 단위로 고른다 — 여기서 따로 고르게 하면
  // 적재는 사내로, 초안은 사외로 가는 상태가 만들어진다.
  const [provider] = useLlmChoice();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WikiSuggestion | null>(null);

  const ask = useCallback(async () => {
    setBusy(true);
    onError(null);
    try {
      setResult(await api.wiki.assist({ stable_id: stableId, task: "concept", provider }));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [stableId, provider, onError]);

  return (
    <div className="assist">
      <div className="assist-row">
        <button disabled={busy} onClick={ask}>
          {busy ? t("adminAssisting") : t("adminAssist")}
        </button>
        <span className="chip">
          {t("adminAssistProvider")}: {provider}
        </span>
        <span className="muted small">{t("adminAssistNote")}</span>
      </div>

      {result && (
        <div className="assist-result">
          <p className="muted small">
            {t("adminAssistProvider")}: <strong>{result.provider}</strong>
            {" · "}
            {result.decision.reason}
          </p>
          {result.overridden && (
            <div className="banner warn" style={{ fontSize: "12.5px" }}>
              {t("adminAssistOverridden", {
                requested: result.requested,
                actual: result.provider,
              })}
            </div>
          )}
          <div
            className={result.numeric_clean ? "banner ok" : "banner error"}
            style={{ fontSize: "12.5px" }}
          >
            {result.numeric_clean
              ? t("adminAssistClean")
              : t("adminAssistInvented", { list: result.invented_numbers.join(", ") })}
          </div>
          <pre className="assist-text">{result.text}</pre>
          <p className="muted small">{t("adminAssistApplyHint")}</p>
        </div>
      )}

      <Reanalysis
        stableId={stableId}
        provider={provider}
        reviewer={reviewer}
        onError={onError}
        onApplied={onApplied}
      />
    </div>
  );
}

/** 재분석 — 원문 발췌를 근거로 **본문 전체**를 다시 쓰고, 사람이 고쳐서 반영한다.
 *
 * 제안을 그대로 저장하지 않는 이유는 둘이다. 검토가 끝난 페이지가 조용히 바뀌면 그
 * 서명이 무엇을 보증하는지 알 수 없고, 서술을 고치라고 부른 모델이 표의 수치를 바꿔
 * 놓는 일이 실제로 일어난다. 그래서 결과는 **편집 가능한 상태**로 보여 주고, 반영은
 * 서버가 수치·구조를 다시 검사한 뒤에만 받는다.
 */
function Reanalysis({
  stableId,
  provider,
  reviewer,
  onError,
  onApplied,
}: {
  stableId: string;
  provider: string;
  reviewer: string;
  onError: (m: string | null) => void;
  onApplied: () => void;
}) {
  const { t } = useLang();
  const [busy, setBusy] = useState<"" | "run" | "apply">("");
  const [result, setResult] = useState<WikiReanalysis | null>(null);
  const [draft, setDraft] = useState("");
  const [applied, setApplied] = useState(false);

  const run = useCallback(async () => {
    setBusy("run");
    setApplied(false);
    onError(null);
    try {
      const r = await api.wiki.reanalyze({ stable_id: stableId, provider });
      setResult(r);
      setDraft(r.text);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy("");
    }
  }, [stableId, provider, onError]);

  const apply = useCallback(async () => {
    setBusy("apply");
    onError(null);
    try {
      await api.wiki.applyBody(stableId, {
        body: draft,
        actor: reviewer,
        note: `재분석 반영 (${result?.provider ?? provider})`,
      });
      setApplied(true);
      onApplied();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy("");
    }
  }, [stableId, draft, reviewer, result, provider, onError, onApplied]);

  return (
    <div className="reanalysis">
      <div className="assist-row">
        <button className="primary" disabled={busy !== ""} onClick={run}>
          {busy === "run" ? t("adminReanalyzing") : t("adminReanalyze")}
        </button>
        <span className="muted small">{t("adminReanalyzeNote")}</span>
      </div>

      {result && (
        <div className="assist-result">
          <p className="muted small">
            {t("adminAssistProvider")}: <strong>{result.provider}</strong> ·{" "}
            {t("adminReanalyzeContext", {
              pages: result.context_pages.join(", ") || "—",
              chars: result.context_chars,
            })}
          </p>

          {result.warnings.map((w, i) => (
            <div key={i} className="banner warn" style={{ fontSize: "12.5px" }}>
              {w}
            </div>
          ))}

          <textarea
            className="reanalysis-draft"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
          />

          <div className="assist-row">
            <button
              className="primary"
              disabled={busy !== "" || !draft.trim() || !reviewer.trim()}
              onClick={apply}
              title={reviewer.trim() ? "" : t("adminReviewerHint")}
            >
              {busy === "apply" ? t("adminApplying") : t("adminApply")}
            </button>
            {applied && <span className="chip s-ok">{t("adminApplied")}</span>}
            <span className="muted small">{t("adminApplyNote")}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 무결성 검사
// --------------------------------------------------------------------------- //
function LintTab({
  refresh,
  onError,
}: {
  refresh: number;
  onError: (m: string | null) => void;
}) {
  const { t } = useLang();
  const [lint, setLint] = useState<WikiLint | null>(null);

  useEffect(() => {
    api.wiki.lint().then(setLint).catch((e) => onError(e.message));
  }, [refresh, onError]);

  if (!lint) return <div className="muted pad">{t("loading")}</div>;

  const shown: WikiFinding[] = lint.findings.filter((f) => f.severity !== "info");

  return (
    <div className="admin-lint">
      <div className={lint.deployable ? "banner ok" : "banner error"}>
        <strong>{lint.deployable ? t("adminLintClean") : t("adminLintBlocked")}</strong>
      </div>
      <p className="muted small">{t("adminLintNote")}</p>
      <p className="muted small">
        {Object.entries(lint.counts)
          .map(([sev, n]) => `${t(SEVERITY_KEY[sev] ?? "kbSevInfo")} ${n}`)
          .join(" · ")}
      </p>
      {shown.length === 0 ? (
        <div className="muted pad">{t("kbNoFindings")}</div>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>{t("adminColSeverity")}</th>
              <th>{t("adminColCode")}</th>
              <th>{t("adminColPage")}</th>
              <th>{t("adminColMessage")}</th>
              <th>{t("adminColHint")}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((f, i) => (
              <tr key={i}>
                <td>
                  <span className={`verdict ${SEVERITY_CLASS[f.severity] ?? ""}`}>
                    {t(SEVERITY_KEY[f.severity] ?? "kbSevInfo")}
                  </span>
                </td>
                <td>
                  <code className="inline-code">{f.code}</code>
                </td>
                <td>{f.page}</td>
                <td>{f.message}</td>
                <td className="muted small">{f.hint}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 저널
// --------------------------------------------------------------------------- //
function JournalTab({
  refresh,
  onError,
}: {
  refresh: number;
  onError: (m: string | null) => void;
}) {
  const { t } = useLang();
  const [rows, setRows] = useState<WikiJournalRow[]>([]);

  useEffect(() => {
    api.wiki
      .journal()
      .then((r) => setRows(r.journal))
      .catch((e) => onError(e.message));
  }, [refresh, onError]);

  return (
    <div className="admin-journal">
      <p className="muted small">{t("adminJournalNote")}</p>
      {rows.length === 0 ? (
        <div className="muted pad">{t("adminJournalEmpty")}</div>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>{t("adminColAt")}</th>
              <th>{t("adminColDecision")}</th>
              <th>{t("adminColPage")}</th>
              <th>{t("adminColActor")}</th>
              <th>{t("adminColAck")}</th>
              <th>{t("adminNote")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.at}</td>
                <td>{r.decision}</td>
                <td>
                  <code className="inline-code">{r.stable_id}</code> v{r.version}
                </td>
                <td>{r.actor}</td>
                <td>{r.acknowledged_unverified ? "●" : ""}</td>
                <td>{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
