/** 평가표 — 관리자가 자가진단 설문을 만드는 자리.
 *
 * 회의에서 나온 그대로다: 질문을 등록하고, 라디오로 받을지 체크박스로 받을지
 * 고른다. 100개를 손으로 다 치게 두지 않으려고 sLM 초안 버튼을 붙였다 —
 * **초안일 뿐이고**, 관리자가 고치고 지운 뒤 저장해야 표가 된다.
 *
 * 기준 관리(통제·지표)와 다른 축이다. 저쪽은 기계가 증적으로 확인하는 것이고,
 * 여기는 사람이 채우는 질문지다. 한 화면에 합치면 "이건 증적으로 확인되나,
 * 담당자가 답하나" 가 흐려진다.
 */
import { useCallback, useEffect, useState } from "react";
import { api, type RegSheet, type SheetQuestion, type SheetMeta } from "./api";
import { useLang, type StringKey } from "./i18n";

const SIGNER_KEY = "llmwiki.reg.signer";

function readSigner(): string {
  try {
    return localStorage.getItem(SIGNER_KEY) ?? "gov-officer";
  } catch {
    return "gov-officer";
  }
}

/** 응답 유형의 라벨. 회의에서 쓰신 말(라디오·체크박스)을 그대로 쓴다 —
 *  코드 이름(single·multi)을 화면에 내면 무엇인지 알 수 없다. */
const KIND_LABEL: Record<string, StringKey> = {
  yesno: "shKindYesno",
  single: "shKindSingle",
  multi: "shKindMulti",
  scale: "shKindScale",
  text: "shKindText",
};

/** 보기가 필요한 유형. 여기 들어가면 화면이 보기 입력칸을 연다. */
const NEEDS_OPTIONS = new Set(["single", "multi", "scale"]);

const EMPTY: SheetQuestion = {
  no: 0, text: "", kind: "yesno", options: [], required: true, help: "", item_no: null,
};

export default function Sheets() {
  const { t } = useLang();
  const [meta, setMeta] = useState<SheetMeta | null>(null);
  const [sheets, setSheets] = useState<RegSheet[]>([]);
  const [editing, setEditing] = useState<RegSheet | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.reg
      .sheets()
      .then((r) => {
        setSheets(r.sheets);
        setMeta(r);
      })
      .catch((e) => setError(String(e)));
  }, []);
  useEffect(load, [load]);

  return (
    <section className="sh">
      <header className="svc-head">
        <div>
          <h2>{t("shTitle")}</h2>
          <p className="lede">{t("shLede")}</p>
        </div>
        {!editing && (
          <button
            className="btn"
            onClick={() =>
              setEditing({
                sheet_id: "", title: "", version: 0, status: "draft",
                owner_role: "", questions: [{ ...EMPTY, no: 1 }], note: "",
                saved_by: "", saved_at: "", published_by: "", published_at: "",
              })
            }
          >
            {t("shNew")}
          </button>
        )}
      </header>

      {error && <div className="banner error">{error}</div>}

      {/* 발행이 결재를 거치지 않는다는 사실을 감추지 않는다. */}
      <div className="banner note">{t("shNoApprovalYet")}</div>

      {editing && meta ? (
        <SheetEditor
          meta={meta}
          sheet={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      ) : (
        <div className="sh-list">
          {sheets.length === 0 && <div className="muted pad">{t("shEmpty")}</div>}
          {sheets.map((s) => (
            <article key={s.sheet_id} className="sh-card">
              <header>
                <span className={`chip ${s.status === "published" ? "s-ok" : "s-pending"}`}>
                  {t(s.status === "published" ? "shPublished" : "shDraft")}
                </span>
                <b>{s.title}</b>
                <span className="muted small">v{s.version}</span>
                <span className="muted small">
                  {t("shCount").replace("{n}", String(s.questions.length))}
                </span>
              </header>
              <p className="muted small">
                {t("shSavedBy").replace("{who}", s.saved_by)
                  .replace("{at}", (s.saved_at || "").slice(0, 16).replace("T", " "))}
              </p>
              <div className="sh-actions">
                <button className="btn ghost sm" onClick={() => setEditing(s)}>
                  {t("shEdit")}
                </button>
                {s.status !== "published" && (
                  <button
                    className="btn sm"
                    onClick={() =>
                      api.reg
                        .publishSheet(s.sheet_id, readSigner())
                        .then(load)
                        .catch((e) => setError(String(e)))
                    }
                  >
                    {t("shPublish")}
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------
// 편집기
// --------------------------------------------------------------------------
function SheetEditor({
  meta, sheet, onClose, onSaved,
}: {
  meta: SheetMeta;
  sheet: RegSheet;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useLang();
  const [title, setTitle] = useState(sheet.title);
  const [rows, setRows] = useState<SheetQuestion[]>(
    sheet.questions.length ? sheet.questions : [{ ...EMPTY, no: 1 }]
  );
  const [by, setBy] = useState(readSigner);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // sLM 초안
  const [topic, setTopic] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [draftFrom, setDraftFrom] = useState("");

  const set = (i: number, next: Partial<SheetQuestion>) =>
    setRows((cur) =>
      cur.map((q, j) =>
        j === i
          // 관리자가 손대면 'sLM 초안' 표시를 지운다 — 고친 것은 사람 것이다.
          ? { ...q, ...next, drafted_by_slm: next.text !== undefined ? false : q.drafted_by_slm }
          : q
      )
    );

  const draft = () => {
    setDrafting(true);
    setError("");
    api.reg
      .draftSheet(topic, 6)
      .then((r) => {
        if (!r.ok || r.questions.length === 0) {
          setError(r.reason || t("shDraftFailed"));
          return;
        }
        setDraftFrom(`${r.model}`);
        setRows((cur) => {
          const kept = cur.filter((q) => q.text.trim());
          return [...kept, ...r.questions.map((q, i) => ({
            ...EMPTY, ...q, no: kept.length + i + 1,
          }))];
        });
      })
      .catch((e) => setError(String(e)))
      .finally(() => setDrafting(false));
  };

  const save = () => {
    setBusy(true);
    setError("");
    api.reg
      .saveSheet({
        sheet_id: sheet.sheet_id,
        title,
        by,
        questions: rows.filter((q) => q.text.trim()),
      })
      .then(() => {
        try {
          localStorage.setItem(SIGNER_KEY, by);
        } catch { /* 저장 못 해도 표는 저장됐다 */ }
        onSaved();
      })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <div className="svc-define sh-editor">
      {error && <div className="banner error">{error}</div>}

      <div className="sh-title">
        <label>
          <span>{t("shName")}</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)}
                 placeholder={t("shNameHint")} />
        </label>
        {sheet.version > 0 && (
          <span className="muted small">{t("shNextVersion").replace("{v}", String(sheet.version + 1))}</span>
        )}
      </div>

      {/* ── sLM 초안 ─────────────────────────────────────────────── */}
      <div className="sh-draft">
        <div>
          <b>{t("shDraftTitle")}</b>
          <p className="muted small">{t("shDraftLede")}</p>
        </div>
        <div className="sh-draft-row">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={t("shDraftHint")}
            disabled={drafting}
          />
          <button className="btn ghost" disabled={drafting || !topic.trim()} onClick={draft}>
            {drafting ? t("shDrafting") : t("shDraftGo")}
          </button>
        </div>
        {draftFrom && <p className="muted small">{t("shDraftFrom").replace("{m}", draftFrom)}</p>}
      </div>

      {/* ── 질문 ─────────────────────────────────────────────────── */}
      <h3 className="ctrl-sub">{t("shQuestions")}</h3>
      {rows.map((q, i) => (
        <div className="sh-q" key={i}>
          <div className="sh-q-head">
            <span className="sh-q-no">{i + 1}</span>
            <input
              className="sh-q-text"
              value={q.text}
              onChange={(e) => set(i, { text: e.target.value })}
              placeholder={t("shQHint")}
            />
            {q.drafted_by_slm && <span className="chip s-pending">{t("shFromSlm")}</span>}
            <button className="sb-mini" title={t("shRemove")}
                    onClick={() => setRows((cur) => cur.filter((_, j) => j !== i))}>
              ✕
            </button>
          </div>

          <div className="sh-q-row">
            <label>
              <span>{t("shAnswerKind")}</span>
              <select value={q.kind} onChange={(e) => set(i, { kind: e.target.value })}>
                {meta.kinds.map((k) => (
                  <option key={k} value={k}>{t(KIND_LABEL[k] ?? "shKindYesno")}</option>
                ))}
              </select>
            </label>

            <label>
              <span>{t("shLinkItem")}</span>
              <select
                value={q.item_no ?? ""}
                onChange={(e) => set(i, { item_no: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">{t("shNoItem")}</option>
                {meta.items.map((it) => (
                  <option key={it.no} value={it.no}>{it.no}. {it.label}</option>
                ))}
              </select>
            </label>

            <label className="sh-req">
              <input type="checkbox" checked={q.required}
                     onChange={(e) => set(i, { required: e.target.checked })} />
              <span>{t("shRequired")}</span>
            </label>
          </div>

          {NEEDS_OPTIONS.has(q.kind) && (
            <label className="sh-opts">
              <span>
                {t("shOptions")}
                {q.kind === "scale" && ` · ${t("shScaleDefault")}`}
              </span>
              <input
                value={(q.options ?? []).join(", ")}
                onChange={(e) =>
                  set(i, { options: e.target.value.split(",").map((o) => o.trim()).filter(Boolean) })
                }
                placeholder={
                  q.kind === "scale" ? meta.default_scale.join(", ") : t("shOptionsHint")
                }
              />
            </label>
          )}

          <label className="sh-help">
            <span>{t("shHelp")}</span>
            <input value={q.help ?? ""} onChange={(e) => set(i, { help: e.target.value })}
                   placeholder={t("shHelpHint")} />
          </label>
        </div>
      ))}

      <button className="btn ghost sm"
              onClick={() => setRows((cur) => [...cur, { ...EMPTY, no: cur.length + 1 }])}>
        {t("shAddQ")}
      </button>

      <div className="ctrl-submit">
        <label>
          <span>{t("shAuthor")}</span>
          <input value={by} onChange={(e) => setBy(e.target.value)} />
        </label>
        <button className="btn" disabled={busy || !title.trim()} onClick={save}>
          {busy ? "…" : t("shSave")}
        </button>
        <button className="btn ghost" onClick={onClose}>{t("shCancel")}</button>
      </div>
      <p className="muted small">{t("shSaveNote")}</p>
    </div>
  );
}
