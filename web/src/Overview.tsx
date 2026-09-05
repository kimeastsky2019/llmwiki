/** 개요 — 이 시스템이 무엇을 하는지 한 장으로.
 *
 * 처음 들어온 사람이 메뉴를 하나씩 눌러 보며 구조를 짐작하게 두면, 각 화면이
 * 무슨 관계인지 끝까지 모른다. 그래서 첫 화면을 개요로 둔다.
 *
 * 원래 개요도에서 고친 것 세 가지 —
 *
 *   1. **기준 관리가 빠져 있었다.** 규제 원문·승인 그래프가 하늘에서 떨어진
 *      것처럼 그려져 있었는데, 평가 항목과 지표는 사람이 만들고 고친다.
 *   2. **결재 게이트가 없었다.** 이 제품의 척추다 — 그래프에 쓰는 길은 커밋
 *      결재 하나뿐이다. 그림에 없으면 화살표가 그냥 흘러가는 것으로 읽힌다.
 *   3. **누가 하는지가 없었다.** 단계마다 주체가 다르고, 그것이 역할별로
 *      메뉴가 갈리는 이유다.
 */
import Assist from "./Assist";
import { useLang, type StringKey } from "./i18n";
import type { RoleCode } from "./roles";

export default function Overview({
  roleCode,
  onNavigate,
}: {
  roleCode: RoleCode;
  onNavigate: (path: string) => void;
}) {
  const { t } = useLang();

  return (
    <section className="ov">
      <header className="svc-head">
        <div>
          <h2>{t("ovTitle")}</h2>
          <p className="lede">{t("ovLede")}</p>
        </div>
      </header>

      {/* 기획자에게는 도우미가 먼저다. 이 시스템에서 처음 하는 일이 "빈 폼을
          채우는 것" 이 되지 않게 한다. 다른 역할에게는 띄우지 않는다 — 결재하러
          온 사람에게 기획 대화창은 방해다. */}
      {roleCode === "planner" && <Assist onNavigate={onNavigate} />}

      <PipelineDiagram />

      <div className="ov-cards">
        <article className="ov-card">
          <h3>{t("ovRuleTitle")}</h3>
          <p>{t("ovRuleBody")}</p>
        </article>
        <article className="ov-card">
          <h3>{t("ovGateTitle")}</h3>
          <p>{t("ovGateBody")}</p>
        </article>
        <article className="ov-card">
          <h3>{t("ovLlmTitle")}</h3>
          <p>{t("ovLlmBody")}</p>
        </article>
      </div>

      <div className="ov-go">
        <button className="btn" onClick={() => onNavigate("/reg/process")}>
          {t("ovGoProcess")}
        </button>
        <button className="btn ghost" onClick={() => onNavigate("/reg/services")}>
          {t("ovGoServices")}
        </button>
      </div>
    </section>
  );
}

/** 개요도 — 인라인 SVG.
 *
 *  라이브러리를 쓰지 않는 이유: 이 그림은 한 장이고 바뀌는 값이 없다. 차트
 *  라이브러리를 들이면 번들만 커지고, 글자 크기·색이 앱과 따로 논다.
 *  색은 CSS 변수로 받아 KO/EN·테마와 함께 움직인다. */
function PipelineDiagram() {
  const { t } = useLang();

  /** 파이프라인 6단계. x 는 카드 왼쪽 좌표. */
  const stages: { no: string; head: StringKey; sub: StringKey; who: StringKey }[] = [
    { no: "②", head: "ovS2", sub: "ovS2Sub", who: "ovS2Who" },
    { no: "③", head: "ovS3", sub: "ovS3Sub", who: "ovS3Who" },
    { no: "④", head: "ovS4", sub: "ovS4Sub", who: "ovS4Who" },
    { no: "⑤", head: "ovS5", sub: "ovS5Sub", who: "ovS5Who" },
    { no: "⑥", head: "ovS6", sub: "ovS6Sub", who: "ovS6Who" },
  ];

  const CARD_W = 176;
  const GAP = 22;
  const X0 = 30;
  const ROW_Y = 250;
  const CARD_H = 96;

  return (
    <figure className="ov-fig">
      <svg
        viewBox="0 0 1020 470"
        role="img"
        aria-label={t("ovDiagramAlt")}
        className="ov-svg"
      >
        <defs>
          <marker id="ovArrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
          </marker>
        </defs>

        {/* ── 입력 두 갈래 ─────────────────────────────────────────── */}
        <g className="ov-src ov-src-code">
          <rect x={X0} y="24" width="420" height="82" rx="14" />
          <text x={X0 + 210} y="54" textAnchor="middle" className="ov-h">
            {t("ovSrcCode")}
          </text>
          <text x={X0 + 210} y="80" textAnchor="middle" className="ov-sub">
            {t("ovSrcCodeSub")}
          </text>
        </g>

        <g className="ov-src ov-src-reg">
          <rect x="570" y="24" width="420" height="82" rx="14" />
          <text x="780" y="54" textAnchor="middle" className="ov-h">
            {t("ovSrcReg")}
          </text>
          <text x="780" y="80" textAnchor="middle" className="ov-sub">
            {t("ovSrcRegSub")}
          </text>
        </g>

        {/* 기준 관리 — 규제 쪽 입력을 사람이 만들고 고친다는 것을 보인다.
            원래 그림에 없어서 규제 그래프가 저절로 있는 것처럼 읽혔다. */}
        <g className="ov-feed">
          <rect x="662" y="128" width="236" height="40" rx="10" />
          <text x="780" y="153" textAnchor="middle" className="ov-feed-t">
            {t("ovCriteria")}
          </text>
          <path d="M780,128 L780,112" markerEnd="url(#ovArrow)" />
        </g>

        {/* 두 입력이 ② 로 모인다 */}
        <g className="ov-flow">
          <path d={`M${X0 + 210},106 L${X0 + 210},196 L${X0 + 88},196 L${X0 + 88},${ROW_Y - 8}`}
                markerEnd="url(#ovArrow)" />
          <path d="M780,168 L780,196 L118,196" />
        </g>

        {/* ── 결재 게이트 ──────────────────────────────────────────
            이 제품의 척추. 그래프에 쓰는 길은 이것 하나뿐이라, 파이프라인
            위에 띠로 깔아 ②·④ 가 여기를 지난다는 것을 보인다. */}
        <g className="ov-gate">
          <rect x={X0} y="208" width="960" height="26" rx="8" />
          <text x={X0 + 12} y="226" className="ov-gate-t">{t("ovGateBand")}</text>
        </g>

        {/* ── 파이프라인 6단계 ─────────────────────────────────────── */}
        {stages.map((s, i) => {
          const x = X0 + i * (CARD_W + GAP);
          return (
            <g key={s.no} className={`ov-stage ${i === 3 ? "ov-stage-rule" : ""}`}>
              <rect x={x} y={ROW_Y} width={CARD_W} height={CARD_H} rx="12" />
              <text x={x + CARD_W / 2} y={ROW_Y + 30} textAnchor="middle" className="ov-h">
                {s.no} {t(s.head)}
              </text>
              <text x={x + CARD_W / 2} y={ROW_Y + 54} textAnchor="middle" className="ov-sub">
                {t(s.sub)}
              </text>
              <text x={x + CARD_W / 2} y={ROW_Y + 79} textAnchor="middle" className="ov-who">
                {t(s.who)}
              </text>
              {i < stages.length - 1 && (
                <path
                  className="ov-arrow"
                  d={`M${x + CARD_W + 2},${ROW_Y + CARD_H / 2} L${x + CARD_W + GAP - 4},${ROW_Y + CARD_H / 2}`}
                  markerEnd="url(#ovArrow)"
                />
              )}
            </g>
          );
        })}

        {/* ── ⑦ 상시로 도는 것 ─────────────────────────────────────── */}
        <g className="ov-always">
          <path d={`M${X0 + 6},${ROW_Y + CARD_H + 18} L985,${ROW_Y + CARD_H + 18}`} />
          <text x="508" y={ROW_Y + CARD_H + 46} textAnchor="middle" className="ov-sub">
            {t("ovAlways")}
          </text>
        </g>
      </svg>
      <figcaption className="muted small">{t("ovDiagramCaption")}</figcaption>
    </figure>
  );
}
