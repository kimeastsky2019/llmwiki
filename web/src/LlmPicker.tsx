import { useEffect, useState } from "react";
import { api, type KbDestination } from "./api";
import { useLang } from "./i18n";
import { useLlmChoice } from "./llmChoice";

/** 사내 / 외부 LLM 선택 — 보고서 지식화 솔루션 전체에 적용된다.
 *
 * 목록은 서버(`/api/kb/health`)가 준다. 화면이 공급자 목록을 따로 들고 있으면
 * 공급자가 늘었을 때 한쪽만 갱신되어 **표시와 판정이 어긋난다** — 이 도메인에서
 * 그것은 국외 이전 여부를 잘못 표시하는 일이다.
 */
export default function LlmPicker() {
  const { t } = useLang();
  const [provider, setProvider] = useLlmChoice();
  const [destinations, setDestinations] = useState<KbDestination[]>([]);

  useEffect(() => {
    api.kb
      .health()
      .then((h) => {
        setDestinations(h.destinations);
        // 저장된 선택이 목록에 없으면(설정이 바뀐 경우) 첫 항목으로 맞춘다.
        if (h.destinations.length && !h.destinations.some((d) => d.provider === provider)) {
          setProvider(h.destinations[0].provider);
        }
      })
      .catch(() => setDestinations([]));
    // provider 를 의존성에 넣으면 고를 때마다 다시 물어본다 — 목록은 한 번이면 된다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (destinations.length === 0) return null;
  const chosen = destinations.find((d) => d.provider === provider);

  return (
    <div className="llm-picker">
      <span className="llm-picker-label">{t("llmChoice")}</span>
      <select value={provider} onChange={(e) => setProvider(e.target.value)}>
        {destinations.map((d) => (
          <option key={d.provider} value={d.provider}>
            {d.name}
          </option>
        ))}
      </select>
      <span className={`llm-flag ${chosen?.cross_border ? "abroad" : "domestic"}`}>
        {chosen?.cross_border ? t("llmAbroad") : t("llmDomestic")}
      </span>
      <span className="llm-picker-note">
        {chosen?.cross_border ? t("llmAbroadNote") : t("llmDomesticNote")}
      </span>
    </div>
  );
}
