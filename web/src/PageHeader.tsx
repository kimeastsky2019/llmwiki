/**
 * 화면 머리말 — "지금 어디에 있는가 → 무엇이 문제인가 → 다음에 무엇을 하는가".
 *
 * 리디자인 가이드 01·03: 지금은 설명·경고·조작·상태가 같은 무게로 깔려 있어
 * 첫 화면에서 핵심 행동이 묻힌다. 그래서 순서를 뒤집는다 —
 * **요약 상태 → 대표 행동 → 상세 정보**.
 *
 * 법적 고지는 숨기지 않는다. 기본은 한 줄 요약이고 눌러야 전문이 펼쳐진다.
 * 모든 화면에 같은 주황 박스를 상시로 띄우면 경고의 긴급도가 오히려 죽는다.
 */
import { useState, type ReactNode } from "react";

export type HeaderStat = {
  label: string;
  value: ReactNode;
  tone?: "ok" | "review" | "blocked" | "idle";
};

export default function PageHeader({
  title,
  lede,
  stats = [],
  action,
  notice,
  noticeSummary,
}: {
  title: string;
  /** 제목 아래 한 줄. 두 줄을 넘기지 않는다. */
  lede?: ReactNode;
  /** 현재 상태 요약 — 판단에 쓰는 숫자만. */
  stats?: HeaderStat[];
  /** 이 화면의 대표 행동. 헤더 우측에 고정된다. */
  action?: ReactNode;
  /** 접어 둘 전문(법적 고지 등) */
  notice?: ReactNode;
  /** 접힌 상태에서 보이는 한 줄 */
  noticeSummary?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <header className="page-header">
      <div className="page-header-top">
        <div className="page-header-title">
          <h1>{title}</h1>
          {lede && <p className="lede">{lede}</p>}
        </div>
        {action && <div className="page-header-action">{action}</div>}
      </div>

      {stats.length > 0 && (
        <div className="page-header-stats">
          {stats.map((s) => (
            <div key={s.label} className={`hstat ${s.tone ?? "idle"}`}>
              <span className="hstat-value">{s.value}</span>
              <span className="hstat-label">{s.label}</span>
            </div>
          ))}
        </div>
      )}

      {notice && (
        <div className="page-notice">
          <button
            type="button"
            className="page-notice-toggle"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <span aria-hidden>ⓘ</span>
            <span>{noticeSummary ?? "안내"}</span>
            <span className="page-notice-caret" aria-hidden>{open ? "▲" : "▼"}</span>
          </button>
          {open && <div className="page-notice-body">{notice}</div>}
        </div>
      )}
    </header>
  );
}
