import { useCallback, useEffect, useState } from "react";
import { api, type EngineInfo, type EngineStatus } from "./api";
import { useLang, type StringKey } from "./i18n";
import { SOLUTIONS } from "./solutions";

const NAME_KEY: Record<string, StringKey> = {
  sllm: "engSllm",
  grok: "engGrok",
  rag: "engRag",
  aigov: "engAigov",
};

const ROLE_KEY: Record<string, StringKey> = {
  sllm: "engSllmRole",
  grok: "engGrokRole",
  rag: "engRagRole",
  aigov: "engAigovRole",
};

/** 상태 → 색. `idle` 은 고장이 아니라 **아직 자료가 없음**이다. 같은 빨간불로
 *  보여 주면 멀쩡한 시스템을 고치려 든다. */
const STATUS_CLASS: Record<EngineStatus, string> = {
  ok: "eng-ok",
  idle: "eng-idle",
  unavailable: "eng-off",
};

const STATUS_KEY: Record<EngineStatus, StringKey> = {
  ok: "engStatusOk",
  idle: "engStatusIdle",
  unavailable: "engStatusOff",
};

export function useEngines(refreshKey = 0) {
  const [engines, setEngines] = useState<EngineInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.engines
      .list()
      .then((r) => {
        setEngines(r.engines);
        setErr(null);
      })
      .catch((e) => setErr(e.message));
  }, [refreshKey]);

  return { engines, err };
}

/** 사이드바 바닥의 엔진 표시줄. 두 솔루션 어디에 있든 같은 값을 본다. */
export default function EngineBar({ onOpen }: { onOpen: () => void }) {
  const { t } = useLang();
  const { engines } = useEngines();

  return (
    <button className="engine-bar" onClick={onOpen} title={t("engBarHint")}>
      <span className="engine-bar-label">{t("engLayer")}</span>
      <span className="engine-bar-dots">
        {(engines ?? []).map((e) => (
          <span key={e.code} className={`eng-dot ${STATUS_CLASS[e.status]}`}>
            {t(NAME_KEY[e.code] ?? "engRag")}
          </span>
        ))}
        {!engines && <span className="muted small">{t("loading")}</span>}
      </span>
    </button>
  );
}

/** 엔진 레이어 전체 화면 — 어떤 엔진이 어느 솔루션에서 무슨 일을 하는지. */
export function EngineLayer({ onNavigate }: { onNavigate: (path: string) => void }) {
  const { t } = useLang();
  const [refreshKey, setRefreshKey] = useState(0);
  const { engines, err } = useEngines(refreshKey);
  const [routing, setRouting] = useState<
    { task: string; acl: string; provider: string; reason: string }[]
  >([]);

  useEffect(() => {
    api.engines
      .list()
      .then((r) => setRouting(r.routing.examples))
      .catch(() => setRouting([]));
  }, [refreshKey]);

  const refresh = useCallback(() => {
    api.engines.list(true).finally(() => setRefreshKey((n) => n + 1));
  }, []);

  return (
    <div className="page engines">
      <h1>{t("engLayer")}</h1>
      <p className="lede">{t("engLede")}</p>
      {err && <div className="banner error">{err}</div>}

      <button className="tables-link" onClick={refresh}>
        {t("engRefresh")}
      </button>

      <div className="engine-grid">
        {(engines ?? []).map((e) => (
          <section key={e.code} className={`engine-card ${STATUS_CLASS[e.status]}`}>
            <header>
              <span className={`eng-dot ${STATUS_CLASS[e.status]}`} />
              <h2>{t(NAME_KEY[e.code] ?? "engRag")}</h2>
              <span className="chip">{t(STATUS_KEY[e.status])}</span>
            </header>
            <p className="muted small">{t(ROLE_KEY[e.code] ?? "engRagRole")}</p>

            <dl className="engine-detail">
              {e.detail.model && (
                <>
                  <dt>{t("engModel")}</dt>
                  <dd>
                    <code className="inline-code">{e.detail.model}</code>
                  </dd>
                </>
              )}
              {e.detail.base_url && (
                <>
                  <dt>{t("engEndpoint")}</dt>
                  <dd>
                    <code className="inline-code">{e.detail.base_url}</code>
                  </dd>
                </>
              )}
              {typeof e.detail.wiki_pages === "number" && (
                <>
                  <dt>{t("engIndexed")}</dt>
                  <dd>
                    {t("engIndexedValue", {
                      wiki: e.detail.wiki_pages,
                      kb: Number(e.detail.kb_documents ?? 0),
                    })}
                  </dd>
                </>
              )}
              {typeof e.detail.nodes === "number" && (
                <>
                  <dt>{t("engGraph")}</dt>
                  <dd>
                    {t("engGraphValue", {
                      nodes: e.detail.nodes,
                      ruleset: String(e.detail.ruleset ?? ""),
                    })}
                  </dd>
                </>
              )}
              {e.detail.destination && (
                <>
                  <dt>{t("kbDestination")}</dt>
                  <dd>
                    {String(e.detail.destination)}{" "}
                    {e.detail.cross_border ? t("kbDestOverseas") : t("kbDestDomestic")}
                  </dd>
                </>
              )}
            </dl>

            {e.detail.reason && (
              <div className={e.status === "idle" ? "banner warn" : "banner error"}>
                <strong>{e.detail.reason}</strong>
                {e.detail.hint && <pre>{e.detail.hint}</pre>}
              </div>
            )}

            <p className="muted small engine-used">
              {t("engUsedBy")}:{" "}
              {SOLUTIONS.filter((s) => s.engines.includes(e.code))
                .map((s) => t(s.labelKey))
                .join(" · ")}
            </p>
          </section>
        ))}
      </div>

      <h2 className="engine-section">{t("engRouting")}</h2>
      <p className="muted small">{t("engRoutingNote")}</p>
      <table className="grid engine-routing">
        <thead>
          <tr>
            <th>{t("engTask")}</th>
            <th>{t("wikiAclLabel")}</th>
            <th>{t("adminAssistProvider")}</th>
            <th>{t("engReason")}</th>
          </tr>
        </thead>
        <tbody>
          {routing.map((r, i) => (
            <tr key={i}>
              <td>
                <code className="inline-code">{r.task}</code>
              </td>
              <td>
                <span className="chip acl">{r.acl}</span>
              </td>
              <td>
                <strong>{r.provider}</strong>
              </td>
              <td className="muted small">{r.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <button className="tables-link" onClick={() => onNavigate("/kb")}>
        {t("kbLink")}
      </button>
    </div>
  );
}
