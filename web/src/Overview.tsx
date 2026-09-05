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
import { guide, role as roleOf, type RoleCode } from "./roles";

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
          <h2>{t(`ovTitle_${roleCode}` as StringKey)}</h2>
          <p className="lede">{t(`ovLede_${roleCode}` as StringKey)}</p>
        </div>
        <span className="chip">{t(roleOf(roleCode).labelKey)}</span>
      </header>

      {/* 기획자에게는 도우미가 먼저다. 이 시스템에서 처음 하는 일이 "빈 폼을
          채우는 것" 이 되지 않게 한다. 다른 역할에게는 띄우지 않는다 — 결재하러
          온 사람에게 기획 대화창은 방해다. */}
      {roleCode === "planner" && <Assist onNavigate={onNavigate} />}

      {/* 내가 할 일 — 역할마다 다르다. 개요를 읽고 나서 어디로 갈지 모르면
          개요가 제 몫을 못 한 것이다. */}
      <ol className="ov-steps">
        {guide(roleCode).steps.map((step, i) => (
          <li key={step.path}>
            <button className="ov-step" onClick={() => onNavigate(step.path)}>
              <span className="ov-step-no">{i + 1}</span>
              <span>
                <b>{t(step.labelKey)}</b>
                <span className="muted small">{t(step.descKey)}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>

      <PipelineDiagram roleCode={roleCode} onNavigate={onNavigate} />

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
function PipelineDiagram({
  roleCode,
  onNavigate,
}: {
  roleCode: RoleCode;
  onNavigate: (path: string) => void;
}) {
  const { t } = useLang();
  // 이 역할이 만지는 단계. 비어 있으면(운영) 아무것도 죽이지 않는다 —
  // 전부 흐리게 만들면 그림이 '내 일이 없다' 로 읽힌다.
  const owns = new Set(guide(roleCode).owns);

  /** 파이프라인 6단계. x 는 카드 왼쪽 좌표. */
  const stages: { no: string; key: string; head: StringKey; sub: StringKey; who: StringKey }[] = [
    { no: "②", key: "define", head: "ovS2", sub: "ovS2Sub", who: "ovS2Who" },
    { no: "③", key: "grade", head: "ovS3", sub: "ovS3Sub", who: "ovS3Who" },
    { no: "④", key: "controls", head: "ovS4", sub: "ovS4Sub", who: "ovS4Who" },
    { no: "⑤", key: "assess", head: "ovS5", sub: "ovS5Sub", who: "ovS5Who" },
    { no: "⑥", key: "confirm", head: "ovS6", sub: "ovS6Sub", who: "ovS6Who" },
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

        {/* ── 입력 세 갈래 ───────────────────────────────────────────
            코드 · 데이터 · 규제. 앞의 둘은 운영 자산에서 나온 **사실**이고,
            셋째는 우리가 지켜야 하는 **기준**이다. 성격이 달라 색을 가른다. */}
        <g className="ov-src ov-src-code ov-clickable"
           onClick={() => onNavigate("/programs")}
           role="link" tabIndex={0}
           onKeyDown={(e) => e.key === "Enter" && onNavigate("/programs")}>
          <rect x={X0} y="20" width="290" height="78" rx="14" />
          <text x={X0 + 145} y="48" textAnchor="middle" className="ov-h">
            {t("ovSrcCode")}
          </text>
          <text x={X0 + 145} y="72" textAnchor="middle" className="ov-sub">
            {t("ovSrcCodeSub")}
          </text>
          <text x={X0 + 280} y="40" textAnchor="end" className="ov-go">→</text>
        </g>

        {/* 데이터 구축 · 분석 — 코드와 나란한 또 하나의 사실. 이 상자가 없으면
            "편향은 어디서 나오나" 에 그림이 답하지 못한다. */}
        <g className="ov-src ov-src-data ov-clickable"
           onClick={() => onNavigate("/data")}
           role="link" tabIndex={0}
           onKeyDown={(e) => e.key === "Enter" && onNavigate("/data")}>
          <rect x="365" y="20" width="290" height="78" rx="14" />
          <text x="510" y="48" textAnchor="middle" className="ov-h">
            {t("ovSrcData")}
          </text>
          <text x="510" y="72" textAnchor="middle" className="ov-sub">
            {t("ovSrcDataSub")}
          </text>
          <text x="645" y="40" textAnchor="end" className="ov-go">→</text>
        </g>

        <g className="ov-src ov-src-reg">
          <rect x="700" y="20" width="290" height="78" rx="14" />
          <text x="845" y="48" textAnchor="middle" className="ov-h">
            {t("ovSrcReg")}
          </text>
          <text x="845" y="72" textAnchor="middle" className="ov-sub">
            {t("ovSrcRegSub")}
          </text>
        </g>

        {/* 기준 관리 — 규제 쪽 입력을 사람이 만들고 고친다는 것을 보인다. */}
        <g className="ov-feed">
          <rect x="727" y="118" width="236" height="38" rx="10" />
          <text x="845" y="142" textAnchor="middle" className="ov-feed-t">
            {t("ovCriteria")}
          </text>
          <path d="M845,118 L845,104" markerEnd="url(#ovArrow)" />
        </g>

        {/* 코드·데이터는 ③ 위험등급의 근거가 되고, 코드는 ② 서비스 정의도 만든다.
            규제·기준은 ④ 통제·증적으로 간다. 화살표가 그 사실을 말한다. */}
        <g className="ov-flow">
          <path d={`M${X0 + 145},98 L${X0 + 145},176 L${X0 + 88},176 L${X0 + 88},${ROW_Y - 8}`}
                markerEnd="url(#ovArrow)" />
          <path d={`M510,98 L510,176 L${X0 + 88 + CARD_W + GAP},176 L${X0 + 88 + CARD_W + GAP},${ROW_Y - 8}`}
                markerEnd="url(#ovArrow)" />
          <path d={`M845,156 L845,176 L${X0 + 88 + 2 * (CARD_W + GAP)},176 L${X0 + 88 + 2 * (CARD_W + GAP)},${ROW_Y - 8}`}
                markerEnd="url(#ovArrow)" />
        </g>

        {/* 32항목 후보가 어디서 오는지 — 세 갈래다. 자가진단은 그림 밖(사람)이라
            글자로만 적는다. */}
        <text x="510" y="196" textAnchor="middle" className="ov-note">
          {t("ovThreeSources")}
        </text>

        {/* ── 결재 게이트 ──────────────────────────────────────────
            이 제품의 척추. 그래프에 쓰는 길은 이것 하나뿐이라, 파이프라인
            위에 띠로 깔아 ②·④ 가 여기를 지난다는 것을 보인다. */}
        <g className="ov-gate">
          <rect x={X0} y="210" width="960" height="26" rx="8" />
          <text x={X0 + 12} y="228" className="ov-gate-t">{t("ovGateBand")}</text>
        </g>

        {/* ── 파이프라인 6단계 ─────────────────────────────────────── */}
        {stages.map((s, i) => {
          const x = X0 + i * (CARD_W + GAP);
          return (
            <g
              key={s.no}
              className={[
                "ov-stage",
                i === 3 ? "ov-stage-rule" : "",
                owns.size && !owns.has(s.key) ? "ov-stage-off" : "",
                owns.has(s.key) ? "ov-stage-mine" : "",
              ].filter(Boolean).join(" ")}
            >
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
        {/* 운영은 파이프라인의 한 단계를 맡지 않는다 — 배포 뒤에 상시로 도는
            ⑦ 이 그 역할의 자리다. 그래서 운영일 때는 이 줄을 살린다. */}
        <g className={`ov-always ${roleCode === "operator" ? "ov-always-mine" : ""}`}>
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
