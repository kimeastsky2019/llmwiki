import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  securityLevel: "strict",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif",
  themeVariables: {
    primaryColor: "#eef2ff",
    primaryBorderColor: "#6366f1",
    primaryTextColor: "#1e1b4b",
    lineColor: "#94a3b8",
    fontSize: "13px",
  },
});

let seq = 0;

export default function Mermaid({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const id = `mmd-${seq++}`;
    mermaid
      .render(id, chart)
      .then(({ svg }) => {
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (error) {
    return (
      <div className="mermaid-error">
        <strong>흐름도를 그릴 수 없습니다.</strong>
        <pre>{error}</pre>
        <pre>{chart}</pre>
      </div>
    );
  }
  return <div className="mermaid-box" ref={ref} />;
}
