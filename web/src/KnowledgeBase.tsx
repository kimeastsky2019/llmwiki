import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type KbAnalysis,
  type KbDestination,
  type KbDocument,
  type KbFinding,
  type KbHealth,
  type KbHit,
  type KbPreview,
  type KbSector,
  type KbStats,
} from "./api";
import { useLang, type StringKey } from "./i18n";
import { useLlmChoice } from "./llmChoice";
import { useFileDrop } from "./useFileDrop";

export type KbTab = "analyze" | "documents" | "search";

export const KB_TABS: KbTab[] = ["analyze", "documents", "search"];

type DetailTab = "channels" | "gate" | "coverage" | "ontology";

const DETAIL_TABS: DetailTab[] = ["channels", "gate", "coverage", "ontology"];

/** 심각도 → CSS 클래스. 색은 화면에서만 쓰고 판정은 서버가 정한다. */
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

const CHANNEL_KEY: Record<string, StringKey> = {
  text: "kbChannelText",
  table: "kbChannelTable",
  image: "kbChannelImage",
  excel: "kbChannelExcel",
};

const CHANNEL_NOTE: Record<string, StringKey> = {
  text: "kbChannelTextNote",
  table: "kbChannelTableNote",
  image: "kbChannelImageNote",
  excel: "kbChannelExcelNote",
};

/** 내용을 볼 수 있는 채널. 엑셀은 표 채널을 시트로 다시 쓴 것이라 여기 없다 —
 *  같은 표를 두 번 보여주면 어느 쪽이 원본인지 알 수 없다. */
const PREVIEW_CHANNELS = ["text", "table", "image"] as const;

type PreviewChannel = (typeof PREVIEW_CHANNELS)[number];

const IMAGE_KIND_KEY: Record<string, StringKey> = {
  photo: "kbImgPhoto",
  drawing: "kbImgDrawing",
  chart: "kbImgChart",
  logo: "kbImgLogo",
  unknown: "kbImgUnknown",
};

export default function KnowledgeBase({
  tab,
  onTab,
}: {
  tab: KbTab;
  onTab: (t: KbTab) => void;
}) {
  const { t } = useLang();
  const [health, setHealth] = useState<KbHealth | null>(null);
  const [sectors, setSectors] = useState<KbSector[]>([]);
  const [err, setErr] = useState<string | null>(null);
  // 적재가 일어나면 올려서 목록·검색을 다시 읽게 한다
  const [refresh, setRefresh] = useState(0);
  // 이 문서를 보낼 LLM. 국외 이전 해당성이 여기서 갈리므로 분석 탭이 아니라 화면
  // 전체가 들고 있는다 — 머리말의 '도달하는 곳' 이 선택과 따로 놀면 안 된다.
  // 공급자 선택은 이 화면이 아니라 **보고서 지식화 솔루션 전체**의 것이다.
  // 적재와 위키 초안 제안이 각자 들고 있으면 한쪽만 사외로 나간다.
  const [provider, setProvider] = useLlmChoice();

  useEffect(() => {
    api.kb
      .health()
      .then((h) => {
        setHealth(h);
        // 서버 기본값이 고를 수 있는 값이면 그대로 둔다. 화면이 임의로 다른 값을
        // 띄우면 아무것도 안 골랐을 때의 판정 기준과 표시가 어긋난다.
        //
        // 다만 사용자가 이미 고른 값이 있으면 건드리지 않는다. 이 선택은 이 화면이
        // 아니라 솔루션 전체의 것이라, 여기서 덮어쓰면 화면을 옮길 때마다 사내로
        // 되돌아간다 — 골랐다고 믿는 사용자와 실제 경로가 어긋난다.
        const fallback = h.destinations[0]?.provider ?? "";
        const known = h.destinations.some((d) => d.provider === provider);
        if (!known) {
          setProvider(
            h.destinations.some((d) => d.provider === h.destination.provider)
              ? h.destination.provider
              : fallback
          );
        }
      })
      .catch((e) => setErr(e.message));
    api.kb.sectors().then((r) => setSectors(r.sectors)).catch((e) => setErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 표시도 판정도 같은 한 줄에서 나온다.
  const destination: KbDestination | null = health
    ? health.destinations.find((d) => d.provider === provider) ?? health.destination
    : null;

  return (
    <div className="page kb">
      <h1>{t("kbTitle")}</h1>
      <p className="lede">{t("kbLede")}</p>

      {/* AI기본법 제31조제1항 — 사전 고지. 결과가 있든 없든 상시 노출한다. */}
      <div className="banner warn kb-notice">
        {t("kbPriorNotice")} <span className="muted small">{t("kbPriorNoticeLaw")}</span>
      </div>

      {/* 이미지 OCR 만 빠진 상태는 고장이 아니다 — 그래서 빨간 배너가 아니라 주의로
          알린다. 올리고 나서 '아무것도 없음' 을 보면 파일이 빈 것인지 도구가 없는
          것인지 알 수 없다. */}
      {health?.parser_ready.formats && !health.parser_ready.formats.image.ok && (
        <div className="banner warn small">
          {t("kbImageOcrOff")} <span className="muted">{health.parser_ready.formats.image.reason}</span>
        </div>
      )}

      {health && !health.parser_ready.ok && (
        <div className="banner error">
          <strong>{health.parser_ready.reason}</strong>
          <pre>{health.parser_ready.hint}</pre>
        </div>
      )}

      {health && destination && (
        <p className="muted small kb-dest">
          {t("kbDestination")}: <strong>{destination.name}</strong>{" "}
          {destination.cross_border ? t("kbDestOverseas") : t("kbDestDomestic")}
          {destination.note ? ` — ${destination.note}` : ""}
          {" · "}
          {t("kbOntologyVersion", { version: health.ontology })}
        </p>
      )}

      <div className="reg-tabs" role="tablist">
        {KB_TABS.map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            onClick={() => onTab(key)}
          >
            {t(
              key === "analyze"
                ? "kbTabAnalyze"
                : key === "documents"
                  ? "kbTabDocuments"
                  : "kbTabSearch"
            )}
          </button>
        ))}
      </div>

      {err && <div className="banner error">{err}</div>}

      {tab === "analyze" && (
        <AnalyzeTab
          sectors={sectors}
          destinations={health?.destinations ?? []}
          provider={provider}
          onProvider={setProvider}
          ready={health?.parser_ready.ok !== false}
          accept={(health?.parser_ready.formats?.suffixes ?? [".pdf"]).join(",")}
          onError={setErr}
          onIngested={() => setRefresh((n) => n + 1)}
        />
      )}
      {tab === "documents" && (
        <DocumentsTab key={`d${refresh}`} sectors={sectors} onError={setErr} />
      )}
      {tab === "search" && <SearchTab key={`s${refresh}`} sectors={sectors} onError={setErr} />}
    </div>
  );
}

// --------------------------------------------------------------------------
// 분석 · 적재
// --------------------------------------------------------------------------
function AnalyzeTab({
  sectors,
  destinations,
  provider,
  accept,
  onProvider,
  ready,
  onError,
  onIngested,
}: {
  sectors: KbSector[];
  destinations: KbDestination[];
  provider: string;
  accept: string;
  onProvider: (p: string) => void;
  ready: boolean;
  onError: (e: string | null) => void;
  onIngested: () => void;
}) {
  const { t } = useLang();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sector, setSector] = useState("");
  const [busy, setBusy] = useState<"analyze" | "ingest" | null>(null);
  const [result, setResult] = useState<KbAnalysis | null>(null);
  const [detail, setDetail] = useState<DetailTab>("channels");

  const run = useCallback(
    async (mode: "analyze" | "ingest") => {
      if (!file) return;
      onError(null);
      setBusy(mode);
      setResult(null);
      try {
        const res =
          mode === "analyze"
            ? await api.kb.analyze(file, sector || undefined, provider || undefined)
            : await api.kb.ingest(file, sector || undefined, provider || undefined);
        setResult(res);
        if (mode === "ingest" && res.stored?.stored) onIngested();
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [file, sector, provider, onError, onIngested]
  );

  // 끌어다 놓기. 받지 않는 형식은 그 자리에서 말한다 — '분석하기' 를 누른 뒤에야
  // 서버가 400 을 주면 사용자는 무엇을 잘못했는지 모른다.
  const { isOver, dropProps } = useFileDrop({
    accept,
    disabled: busy !== null,
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
    <>
      <div className="kb-input">
        <button
          className={`kb-drop ${file ? "picked" : ""} ${isOver ? "dropping" : ""}`}
          onClick={() => fileRef.current?.click()}
          {...dropProps}
        >
          <span className="kb-drop-icon">{isOver ? "📥" : "📄"}</span>
          <span>{isOver ? t("kbDropHere") : file ? file.name : t("kbPickFile")}</span>
          <span className="kb-drop-formats">
            {t("kbFormats")} · {t("kbDropHint")}
          </span>
          <input
            ref={fileRef}
            type="file"
            // 목록은 서버(`parser_ready.formats.suffixes`)가 원본이다. 화면이 따로
            // 들고 있으면 형식이 늘었을 때 여기만 낡아 파일 선택창이 막는다.
            accept={accept}
            hidden
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
        </button>

        <label className="kb-sector">
          <span>{t("kbSectorLabel")}</span>
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="">{t("kbSectorAuto")}</option>
            {sectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name} ({s.ksic})
              </option>
            ))}
          </select>
          <span className="muted small">{t("kbSectorHint")}</span>
        </label>

        {/* 사내 GPU 로 돌릴지 클라우드로 보낼지. 개인정보보호법 제28조의8 국외 이전
            해당성이 여기서 갈리므로, 고른 값이 그대로 게이트 판정에 들어간다. */}
        <label className="kb-sector">
          <span>{t("kbProviderLabel")}</span>
          <select
            value={provider}
            onChange={(e) => {
              onProvider(e.target.value);
              // 앞선 결과는 다른 목적지 기준의 판정이다. 남겨 두면 화면 머리말과
              // 게이트 판정이 서로 다른 공급자를 말하게 된다.
              setResult(null);
            }}
          >
            {destinations.map((d) => (
              <option key={d.provider} value={d.provider}>
                {d.name} — {d.cross_border ? t("kbScopeOverseas") : t("kbScopeDomestic")}
              </option>
            ))}
          </select>
          <span className="muted small">{t("kbProviderHint")}</span>
        </label>

        <div className="kb-actions">
          <button className="btn" disabled={!file || !!busy || !ready} onClick={() => run("analyze")}>
            {busy === "analyze" ? t("kbAnalyzing") : t("kbAnalyze")}
          </button>
          <button
            className="btn ghost"
            disabled={!file || !!busy || !ready}
            onClick={() => run("ingest")}
            title={t("kbIngestHint")}
          >
            {busy === "ingest" ? t("kbIngesting") : t("kbIngest")}
          </button>
        </div>
      </div>
      <p className="muted small">{t("kbAnalyzeNote")}</p>

      {result && (
        <>
          <Summary result={result} />
          <GateBanner result={result} />
          {result.stored && <StoredBanner result={result} />}

          <div className="reg-tabs kb-detail-tabs" role="tablist">
            {DETAIL_TABS.map((key) => (
              <button
                key={key}
                role="tab"
                aria-selected={detail === key}
                className={detail === key ? "active" : ""}
                onClick={() => setDetail(key)}
              >
                {t(
                  key === "channels"
                    ? "kbDetailChannels"
                    : key === "gate"
                      ? "kbDetailGate"
                      : key === "coverage"
                        ? "kbDetailCoverage"
                        : "kbDetailOntology"
                )}
              </button>
            ))}
          </div>

          {detail === "channels" && <Channels result={result} />}
          {detail === "gate" && <Gate result={result} />}
          {detail === "coverage" && <Coverage result={result} />}
          {detail === "ontology" && <Ontology result={result} />}

          {/* AI기본법 제31조제2항 — 생성물 표시 */}
          <p className="muted small kb-genmark">
            {t("kbOutputMark")} <span className="muted">{t("kbOutputMarkLaw")}</span>
          </p>
        </>
      )}
    </>
  );
}

function Summary({ result }: { result: KbAnalysis }) {
  const { t } = useLang();
  const cov = Math.round((result.coverage?.coverage ?? 0) * 100);
  return (
    <div className="stats">
      <div className={`stat ${result.needs_review ? "tone-defer" : "tone-ok"}`}>
        <div className="stat-value kb-stat-text">{result.sector_name}</div>
        <div className="stat-label">
          {result.needs_review ? t("kbNeedsReview") : t("kbConfirmed")} ·{" "}
          {Math.round((result.classification?.confidence ?? 0) * 100)}%
        </div>
      </div>
      <div className="stat">
        <div className="stat-value">{cov}%</div>
        <div className="stat-label">
          {t("kbCoverageStat", {
            present: result.coverage?.present?.length ?? 0,
            required: result.coverage?.required ?? 0,
          })}
        </div>
      </div>
      <div className={`stat ${result.upload_allowed ? "tone-ok" : "tone-bad"}`}>
        <div className="stat-value kb-stat-text">{result.gate?.verdict_label}</div>
        <div className="stat-label">
          {t("kbPiiDetected", { n: result.gate?.pii_detected ?? 0 })}
        </div>
      </div>
      <div className="stat">
        <div className="stat-value">{result.graph_stats?.nodes ?? 0}</div>
        <div className="stat-label">
          {t("kbGraphStat", {
            edges: result.graph_stats?.edges ?? 0,
            quantities: result.graph_stats?.quantities ?? 0,
          })}
        </div>
      </div>
    </div>
  );
}

function GateBanner({ result }: { result: KbAnalysis }) {
  const { t } = useLang();
  return (
    <div className={`banner ${result.upload_allowed ? "kb-ok" : "error"}`}>
      <strong>
        {result.upload_allowed
          ? t("kbGateOpen", { partition: result.partition })
          : t("kbGateClosed")}
      </strong>
      <div className="muted small">
        {t("kbRawUpload")}: {result.upload_allowed_raw ? t("kbYes") : t("kbNo")} ·{" "}
        {t("kbMaskingLine", {
          masked: result.masking?.masked_count ?? 0,
          residual: result.masking?.residual_count ?? 0,
        })}
      </div>
    </div>
  );
}

function StoredBanner({ result }: { result: KbAnalysis }) {
  const { t } = useLang();
  const stored = result.stored!;
  if (!stored.stored) {
    return (
      <div className="banner warn">
        <strong>{t("kbNotStored")}</strong>
        <div className="muted small">{stored.skipped}</div>
      </div>
    );
  }
  return (
    <div className="banner kb-ok">
      <strong>{t("kbStored", { n: stored.stored, partition: stored.partition ?? "" })}</strong>
      <div className="muted small">
        {Object.entries(stored.by_channel ?? {})
          .map(([ch, n]) => `${ch} ${n}`)
          .join(" · ")}
      </div>
    </div>
  );
}

function Channels({ result }: { result: KbAnalysis }) {
  const { t } = useLang();
  const s = result.parse_summary;
  const count = (key: string) =>
    key === "excel" ? s?.tables ?? 0 : result.channels?.[key] ?? 0;
  return (
    <>
      <div className="stats">
        {["text", "table", "image", "excel"].map((ch) => (
          <div key={ch} className="stat">
            <div className="stat-value">{count(ch)}</div>
            <div className="stat-label">{t(CHANNEL_KEY[ch])}</div>
            <div className="muted small">{t(CHANNEL_NOTE[ch])}</div>
          </div>
        ))}
      </div>
      <ul className="kb-facts">
        <li>{t("kbFactPages", { pages: s?.pages ?? 0, chars: (s?.text_chars ?? 0).toLocaleString() })}</li>
        <li>
          {t("kbFactTables", {
            tables: s?.tables ?? 0,
            rows: s?.table_rows ?? 0,
            cells: s?.numeric_cells ?? 0,
          })}
        </li>
        <li>
          {t("kbFactImages", { images: s?.images ?? 0 })}{" "}
          {Object.entries(s?.image_kinds ?? {})
            .map(([k, n]) => `${k} ${n}`)
            .join(" · ")}
        </li>
      </ul>
      {(s?.warnings ?? []).map((w) => (
        <div key={w} className="banner warn small">
          ⚠ {w}
        </div>
      ))}
      {result.preview && <ChannelContent preview={result.preview} />}
    </>
  );
}

/** 채널별 실제 내용. 개수 카드 위에서는 무엇이 들어왔는지 확인할 수 없다 —
 *  표가 격자로 살아 있는지, 글이 문단 단위로 끊겼는지는 눈으로 봐야 안다. */
function ChannelContent({ preview }: { preview: KbPreview }) {
  const { t } = useLang();
  const [channel, setChannel] = useState<PreviewChannel>("text");

  // 그림 탭의 배지는 적재되는 것만 센다. 목록에는 로고도 남기지만, 배지가 총 개수를
  // 말하면 위 '그림' 카드의 숫자와 어긋나 어느 쪽이 맞는지 알 수 없게 된다.
  const badge = (c: PreviewChannel) =>
    c === "image" ? preview.image.filter((i) => i.indexed).length : preview[c].length;

  return (
    <section className="kb-preview">
      <div className="kb-preview-head">
        <h3>{t("kbChannelContent")}</h3>
        <p className="muted small">
          {preview.masked ? t("kbPreviewMasked") : t("kbPreviewRaw")}
        </p>
      </div>

      <div className="reg-tabs kb-preview-tabs" role="tablist">
        {PREVIEW_CHANNELS.map((c) => (
          <button
            key={c}
            role="tab"
            aria-selected={channel === c}
            className={channel === c ? "active" : ""}
            onClick={() => setChannel(c)}
          >
            {t(CHANNEL_KEY[c])} <span className="muted">{badge(c)}</span>
          </button>
        ))}
      </div>

      {preview[channel].length === 0 ? (
        <div className="muted pad">{t("kbChannelEmpty")}</div>
      ) : channel === "text" ? (
        <TextChannel blocks={preview.text} />
      ) : channel === "table" ? (
        <TableChannel tables={preview.table} />
      ) : (
        <ImageChannel images={preview.image} />
      )}
    </section>
  );
}

function TextChannel({ blocks }: { blocks: KbPreview["text"] }) {
  const { t } = useLang();
  return (
    <div className="kb-blocks">
      {blocks.map((b) => (
        <article key={b.anchor} className="kb-block">
          <div className="kb-block-head">
            <span className="chip">p.{b.page}</span>
            <code className="inline-code">{b.anchor}</code>
            <span className="muted small">
              {t("kbTextChars", { chars: b.chars.toLocaleString() })}
            </span>
          </div>
          <p className="kb-block-body">{b.content}</p>
        </article>
      ))}
    </div>
  );
}

/** 표는 격자 그대로 그린다. 문장처럼 이어 붙이면 행-열 관계가 다시 깨져,
 *  수치의 출처를 표에서 확인한다는 이 채널의 목적이 사라진다. */
function TableChannel({ tables }: { tables: KbPreview["table"] }) {
  const { t } = useLang();
  return (
    <div className="kb-blocks">
      {tables.map((tb) => (
        <article key={tb.anchor} className="kb-block">
          <div className="kb-block-head">
            <span className="chip">p.{tb.page}</span>
            <code className="inline-code">{tb.anchor}</code>
            {tb.caption && <strong>{tb.caption}</strong>}
            <span className="muted small">
              {t("kbTableNumeric", { cells: tb.numeric_cells })}
            </span>
          </div>
          <div className="table-wrap">
            <table className="reg-table kb-grid">
              {tb.header.length > 0 && (
                <thead>
                  <tr>
                    {tb.header.map((h, i) => (
                      <th key={i}>{h}</th>
                    ))}
                  </tr>
                </thead>
              )}
              <tbody>
                {tb.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {tb.header.length === 0 && (
            <p className="muted small">{t("kbTableNoHeader")}</p>
          )}
        </article>
      ))}
    </div>
  );
}

function ImageChannel({ images }: { images: KbPreview["image"] }) {
  const { t } = useLang();
  const excluded = images.filter((i) => !i.indexed).length;
  return (
    <>
      <div className="kb-images">
        {images.map((im) => (
          <div key={im.anchor} className={`kb-image ${im.indexed ? "" : "excluded"}`}>
            <div className="kb-block-head">
              <span className="chip">p.{im.page}</span>
              <span className="chip">{t(IMAGE_KIND_KEY[im.kind] ?? "kbImgUnknown")}</span>
              {!im.indexed && (
                <span className="verdict v-na">{t("kbImgNotIndexed")}</span>
              )}
            </div>
            <div className="kb-image-cap">
              {im.caption || <span className="muted">{t("kbImgNoCaption")}</span>}
            </div>
            <div className="muted small">
              <code>{im.anchor}</code> · {im.width}×{im.height}
            </div>
          </div>
        ))}
      </div>
      {excluded > 0 && (
        <p className="muted small">{t("kbImgExcluded", { n: excluded })}</p>
      )}
    </>
  );
}

function Gate({ result }: { result: KbAnalysis }) {
  const { t } = useLang();
  const findings: KbFinding[] = result.gate?.findings ?? [];
  if (findings.length === 0) return <div className="muted pad">{t("kbNoFindings")}</div>;
  return (
    <>
      {findings.map((f) => (
        <div key={f.rule} className="kb-finding">
          <div className="kb-finding-head">
            <span className={`verdict ${SEVERITY_CLASS[f.severity]}`}>
              {t(SEVERITY_KEY[f.severity] ?? "kbSevInfo")}
            </span>
            <span className="muted small">
              {f.law} {f.article}
            </span>
            <code className="inline-code">{f.rule}</code>
          </div>
          <div className="kb-finding-title">{f.title}</div>
          <p className="muted">{f.detail}</p>
          {f.samples.length > 0 && (
            <div className="pill-row">
              {f.samples.map((sample) => (
                <code key={sample} className="kb-sample">
                  {sample}
                </code>
              ))}
            </div>
          )}
          {f.remedy && (
            <p className="kb-remedy">
              <strong>{t("kbRemedy")}</strong> — {f.remedy}
            </p>
          )}
        </div>
      ))}
      <p className="muted small">{result.gate?.note}</p>
    </>
  );
}

function Coverage({ result }: { result: KbAnalysis }) {
  const { t } = useLang();
  const cov = result.coverage;
  return (
    <>
      <p className="muted">
        {t("kbUnitBasis")}: <strong>{cov?.unit_basis}</strong> · {cov?.sector_name}
      </p>
      <div className="table-wrap">
        <table className="reg-table">
          <thead>
            <tr>
              <th>{t("kbColMetric")}</th>
              <th>{t("kbColPresence")}</th>
              <th>{t("kbColEvidence")}</th>
            </tr>
          </thead>
          <tbody>
            {(cov?.present ?? []).map((m) => (
              <tr key={m.code}>
                <td>{m.label}</td>
                <td>
                  <span className="verdict v-ok">{t("kbPresent")}</span>
                </td>
                <td>
                  <code className="inline-code">{m.evidence}</code>
                </td>
              </tr>
            ))}
            {(cov?.missing ?? []).map((m) => (
              <tr key={m.code}>
                <td>{m.label}</td>
                <td>
                  <span className="verdict v-bad">{t("kbMissing")}</span>
                </td>
                <td className="muted">—</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">{t("kbCoverageNote")}</p>
    </>
  );
}

function Ontology({ result }: { result: KbAnalysis }) {
  const { t } = useLang();
  const g = result.graph_stats;

  const download = () => {
    if (!result.graph) return;
    const blob = new Blob([JSON.stringify(result.graph, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.doc_hash}_ontology.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <div className="kb-onto-head">
        <p className="muted">{t("kbOntologyNote")}</p>
        {result.graph && (
          <button className="btn small" onClick={download}>
            {t("kbGraphDownload")}
          </button>
        )}
      </div>

      {!result.validation?.ok && (
        <div className="banner error">
          {t("kbSchemaErrors", { n: result.validation?.errors ?? 0 })}
        </div>
      )}

      <div className="kb-onto-grid">
        <div>
          <h3>{t("kbNodeTypes")}</h3>
          {Object.entries(g?.by_type ?? {}).map(([type, n]) => (
            <div key={type} className="kb-kv">
              <span className="muted">{type}</span>
              <span>{n}</span>
            </div>
          ))}
        </div>
        <div>
          <h3>{t("kbDerivations")}</h3>
          {Object.entries(g?.by_derivation ?? {}).map(([d, n]) => (
            <div key={d} className="kb-kv">
              <span className="muted">{d}</span>
              <span>{n}</span>
            </div>
          ))}
          <p className="muted small">{t("kbDerivationNote")}</p>
        </div>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------
// 적재된 문서
// --------------------------------------------------------------------------
function DocumentsTab({
  sectors,
  onError,
}: {
  sectors: KbSector[];
  onError: (e: string | null) => void;
}) {
  const { t } = useLang();
  const [rows, setRows] = useState<KbDocument[] | null>(null);
  const [stats, setStats] = useState<KbStats | null>(null);
  const [sector, setSector] = useState("");

  useEffect(() => {
    api.kb
      .documents(sector || undefined)
      .then((r) => {
        setRows(r.documents);
        setStats(r.stats);
      })
      .catch((e) => onError(e.message));
  }, [sector, onError]);

  if (!rows) return <div className="muted pad">{t("loading")}</div>;

  return (
    <>
      <div className="reg-actions">
        <label className="kb-sector inline">
          <span>{t("kbSectorLabel")}</span>
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="">{t("kbAllSectors")}</option>
            {sectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {stats && (
          <span className="muted small">
            {t("kbStoreStats", { documents: stats.documents, records: stats.records })}
            {stats.masked_all ? ` · ${t("kbAllMasked")}` : ""}
          </span>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">{t("kbNoDocuments")}</p>
          <p className="muted">{t("kbNoDocumentsHint")}</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="reg-table">
            <thead>
              <tr>
                <th>{t("kbColFile")}</th>
                <th>{t("kbColSector")}</th>
                <th>{t("kbColChannels")}</th>
                <th>{t("kbColMasked")}</th>
                <th>{t("kbColVerdict")}</th>
                <th>{t("kbColIngestedAt")}</th>
                <th>{t("kbColExport")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.doc_hash}>
                  <td>
                    {d.filename}
                    <div className="muted small">
                      <code>{d.doc_hash}</code>
                    </div>
                  </td>
                  <td>{d.sector_name}</td>
                  <td>
                    {Object.entries(d.by_channel ?? {})
                      .map(([ch, n]) => `${ch} ${n}`)
                      .join(" · ")}
                  </td>
                  <td className="center">{d.masked ? `● ${d.masked_count}` : ""}</td>
                  <td>{d.verdict}</td>
                  <td className="muted small">{d.ingested_at}</td>
                  <td className="kb-export">
                    <a href={api.kb.excelUrl(d.doc_hash)}>xlsx</a>
                    <a href={api.kb.ttlUrl(d.doc_hash)}>ttl</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
// 채널 검색
// --------------------------------------------------------------------------
function SearchTab({
  sectors,
  onError,
}: {
  sectors: KbSector[];
  onError: (e: string | null) => void;
}) {
  const { t } = useLang();
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("");
  const [channel, setChannel] = useState("");
  const [hits, setHits] = useState<KbHit[] | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits(null);
      return;
    }
    const timer = setTimeout(() => {
      api.kb
        .search(q, sector || undefined, channel || undefined)
        .then((r) => setHits(r.results))
        .catch((e) => onError(e.message));
    }, 250);
    return () => clearTimeout(timer);
  }, [query, sector, channel, onError]);

  return (
    <>
      <p className="muted small">{t("kbSearchNote")}</p>
      <div className="reg-actions">
        <input
          className="kb-query"
          placeholder={t("kbSearchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="kb-sector inline">
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="">{t("kbAllSectors")}</option>
            {sectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="kb-sector inline">
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">{t("kbAllChannels")}</option>
            {["text", "table", "image"].map((ch) => (
              <option key={ch} value={ch}>
                {t(CHANNEL_KEY[ch])}
              </option>
            ))}
          </select>
        </label>
      </div>

      {hits === null ? (
        <div className="muted pad">{t("kbSearchIdle")}</div>
      ) : hits.length === 0 ? (
        <div className="muted pad">{t("noResults")}</div>
      ) : (
        hits.map((h) => (
          <div key={`${h.doc_hash}:${h.anchor}`} className="kb-hit">
            <div className="kb-hit-head">
              <span className="chip">{t(CHANNEL_KEY[h.channel] ?? "kbChannelText")}</span>
              <strong>{h.sector_name}</strong>
              <span className="muted small">
                {h.filename} · p.{h.page ?? "?"} · <code>{h.anchor}</code>
              </span>
            </div>
            <pre className="kb-snippet">{h.snippet}</pre>
          </div>
        ))
      )}
    </>
  );
}
