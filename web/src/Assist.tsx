/** 기획 도우미 — 사내 sLM 과 함께 서비스를 기획하는 자리.
 *
 * AI 서비스기획 역할로 들어오면 첫 화면 맨 위에 선다. 기획자가 이 시스템에서
 * 처음 하는 일이 "빈 폼을 채우는 것" 이 되지 않게 하려는 것이다 — 회의에서
 * 나온 "기획자들을 리마인드 시켜주는 거" 가 이 자리다.
 *
 * 화면이 지키는 것 둘.
 *
 * 1. **판정처럼 보이지 않게 한다.** 답변에 등급·점수가 나올 자리가 없고,
 *    말풍선 아래에 "판정이 아닙니다" 를 항상 붙인다. 조언과 판정이 같은
 *    모양으로 보이면 사람은 둘을 구별하지 않는다.
 * 2. **어디로 나가는지 보인다.** 사내 sLM 인지 외부 모델인지를 답변마다
 *    표시한다. 기획 내용에는 아직 공개 안 된 서비스 계획이 들어간다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AssistReply } from "./api";
import { useLang, type StringKey } from "./i18n";
import Markdown from "./Markdown";

interface Turn {
  role: "user" | "assistant";
  content: string;
  /** 답변이 어느 모델에서 왔는지. 사용자 말풍선에는 없다. */
  from?: { provider: string; model: string; local: boolean };
}

/** 처음 열었을 때 눌러 볼 것. 빈 입력창만 있으면 무엇을 물어야 할지 모른다. */
const SEEDS: StringKey[] = ["asSeed1", "asSeed2", "asSeed3"];

export default function Assist({
  service,
  onNavigate,
}: {
  service?: string;
  /** 답변을 마크다운으로 그린다 — 앱의 렌더러를 그대로 쓴다. 별도로 두면
   *  링크·표 처리가 화면마다 달라진다. */
  onNavigate: (path: string) => void;
}) {
  const { t } = useLang();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [external, setExternal] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [turns, busy]);

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      const next: Turn[] = [...turns, { role: "user", content: message }];
      setTurns(next);
      setDraft("");
      setBusy(true);
      setError("");
      api.reg
        .assist({
          messages: next.map(({ role, content }) => ({ role, content })),
          service,
          allow_external: external,
        })
        .then((r: AssistReply) => {
          if (!r.ok) {
            setError(r.reason || t("asFailed"));
            return;
          }
          setTurns((cur) => [
            ...cur,
            {
              role: "assistant",
              content: r.text,
              from: { provider: r.provider, model: r.model, local: r.local },
            },
          ]);
        })
        .catch((e) => setError(String(e)))
        .finally(() => setBusy(false));
    },
    [busy, external, service, t, turns]
  );

  return (
    <section className="as">
      <div className="as-head">
        <div>
          <h3>{t("asTitle")}</h3>
          <p className="muted small">{t("asLede")}</p>
        </div>
        {/* 어디로 나가는지 사람이 정한다. 조용히 외부로 넘기면 자료 유출이다. */}
        <label className="as-ext" title={t("asExternalHint")}>
          <input
            type="checkbox"
            checked={external}
            onChange={(e) => setExternal(e.target.checked)}
          />
          <span>{t("asExternal")}</span>
        </label>
      </div>

      <div className="as-log" ref={logRef}>
        {turns.length === 0 && (
          <div className="as-empty">
            <p className="muted small">{t("asEmpty")}</p>
            <div className="as-seeds">
              {SEEDS.map((k) => (
                <button key={k} className="btn ghost sm" onClick={() => send(t(k))}>
                  {t(k)}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, i) => (
          <div key={i} className={`as-msg ${turn.role}`}>
            <div className="as-bubble">
              {turn.role === "assistant" ? (
                <Markdown source={turn.content} onNavigate={onNavigate} />
              ) : (
                turn.content
              )}
            </div>
            {turn.from && (
              <div className="as-from">
                <span className={`chip ${turn.from.local ? "s-ok" : "s-pending"}`}>
                  {t(turn.from.local ? "asLocal" : "asRemote")}
                </span>
                <span className="muted small">{turn.from.model}</span>
                {/* 조언과 판정이 같은 모양이면 사람은 둘을 구별하지 않는다. */}
                <span className="muted small as-notverdict">{t("asNotVerdict")}</span>
              </div>
            )}
          </div>
        ))}

        {busy && <div className="as-msg assistant"><div className="as-bubble as-wait">…</div></div>}
      </div>

      {error && <div className="banner error">{error}</div>}

      <form
        className="as-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("asPlaceholder")}
          disabled={busy}
        />
        <button className="btn" type="submit" disabled={busy || !draft.trim()}>
          {t("asSend")}
        </button>
      </form>
      <p className="muted small">{t("asFoot")}</p>
    </section>
  );
}
