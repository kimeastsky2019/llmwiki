import { useEffect, useState } from "react";
import { api, type WikiHealth } from "./api";
import { useLang } from "./i18n";

/** 파이프라인 상태를 **세 개로 나눠** 보여 준다.
 *
 * 하나의 초록/빨강으로 합치면 표현할 수 없는 상태가 있다 —
 * *위키는 제대로 만들어졌는데 원문 수치가 어긋난* 경우다. 이때
 *
 *   생성 = 성공 (26장)
 *   검산 = 불일치 3건  ← **원문의 오류**이지 파이프라인 실패가 아니다
 *   배포 = 가능 (차단 위반 0)
 *
 * 셋을 합쳐 '실패' 로 칠하면 사용자는 파이프라인을 고치려 들고, '성공' 으로 칠하면
 * 틀린 수치가 그대로 인용된다. 그래서 나란히 둔다.
 */
export default function WikiStatusBoard({
  onNavigate,
  compact = false,
  refreshKey = 0,
}: {
  onNavigate: (path: string) => void;
  compact?: boolean;
  refreshKey?: number;
}) {
  const { t } = useLang();
  const [health, setHealth] = useState<WikiHealth | null>(null);

  useEffect(() => {
    api.wiki.health().then(setHealth).catch(() => setHealth(null));
  }, [refreshKey]);

  if (!health) return null;

  const pages = health.store.pages;
  const verified = health.store.numeric_verified;
  const unverified = pages - verified;
  const drafts = health.store.by_status.draft ?? 0;
  const reviewed = health.store.by_status.reviewed ?? 0;
  const blockers = health.lint.counts.blocker ?? 0;
  const errors = health.lint.counts.error ?? 0;

  const cards = [
    {
      key: "build",
      label: t("stBuild"),
      value: t("stBuildValue", { pages }),
      note: t("stBuildNote"),
      tone: pages > 0 ? "ok" : "idle",
      path: "/admin",
    },
    {
      key: "verify",
      label: t("stVerify"),
      value:
        unverified === 0
          ? t("stVerifyClean", { verified })
          : t("stVerifyValue", { unverified, pages }),
      // 검산 불일치는 **원문의 문제**다. 빨강이 아니라 주의로 둔다 —
      // 빨강으로 칠하면 사용자가 파이프라인을 고치려 든다.
      note: t("stVerifyNote"),
      tone: unverified === 0 ? "ok" : "warn",
      path: "/admin/queue",
    },
    {
      key: "deploy",
      label: t("stDeploy"),
      value: health.lint.deployable ? t("stDeployOk") : t("stDeployBlocked"),
      note:
        blockers + errors > 0
          ? t("stDeployIssues", { blockers, errors })
          : t("stDeployNote", { reviewed, drafts }),
      tone: health.lint.deployable ? (drafts > 0 ? "warn" : "ok") : "bad",
      path: "/admin/lint",
    },
  ];

  return (
    <div className={`status-board ${compact ? "compact" : ""}`}>
      {!compact && <h3>{t("stTitle")}</h3>}
      <div className="status-cards">
        {cards.map((c) => (
          <button
            key={c.key}
            className={`status-card tone-${c.tone}`}
            onClick={() => onNavigate(c.path)}
          >
            <span className="status-label">{c.label}</span>
            <span className="status-value">{c.value}</span>
            {!compact && <span className="status-note">{c.note}</span>}
          </button>
        ))}
      </div>
      {!compact && <p className="muted small">{t("stBoardNote")}</p>}
    </div>
  );
}
