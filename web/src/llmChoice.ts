/** 보고서 지식화 솔루션에서 고른 LLM 경로 — 화면 하나가 아니라 **솔루션 전체**의 선택.
 *
 * 지식 데이터베이스 적재와 위키의 서술 초안 제안이 각자 공급자를 들고 있으면,
 * 한쪽은 사내로 다른 쪽은 사외로 나가는 상태가 만들어진다. 그런데 사용자는 화면
 * 상단에서 한 번 골랐다고 믿는다. 그래서 선택을 한 곳에 두고 양쪽이 같은 값을 본다.
 *
 * 기본값은 **사내**다. 기본이 사외 전송이면 언젠가 모르고 내보낸다.
 */
import { useSyncExternalStore } from "react";

const KEY = "llmwiki.report.provider";

/** 아무것도 고르지 않았을 때. 서버의 목적지 목록에 없으면 화면이 첫 항목으로 맞춘다. */
export const DEFAULT_PROVIDER = "ollama";

let current: string = read();
const listeners = new Set<() => void>();

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? DEFAULT_PROVIDER;
  } catch {
    return DEFAULT_PROVIDER;
  }
}

export function getLlmChoice(): string {
  return current;
}

export function setLlmChoice(provider: string): void {
  if (provider === current) return;
  current = provider;
  try {
    localStorage.setItem(KEY, provider);
  } catch {
    /* 프라이빗 모드에서 실패해도 세션 안에서는 동작한다 */
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** 고른 공급자를 구독한다. 어느 화면에서 바꾸든 모든 화면이 같이 바뀐다. */
export function useLlmChoice(): [string, (p: string) => void] {
  const value = useSyncExternalStore(subscribe, getLlmChoice, getLlmChoice);
  return [value, setLlmChoice];
}
