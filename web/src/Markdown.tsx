import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Mermaid from "./Mermaid";

interface Props {
  source: string;
  onNavigate: (path: string) => void;
  /** 절 제목에 id 를 붙인다. 긴 페이지에서 '이 페이지 안에서' 이동에 쓴다. */
  anchors?: boolean;
}

/** 제목 → id. 같은 규칙을 화면 쪽에서도 써야 링크가 맞는다. */
export function headingId(text: string): string {
  return (
    "s-" +
    text
      .trim()
      .toLowerCase()
      .replace(/[^\w가-힣]+/g, "-")
      .replace(/^-+|-+$/g, "")
  );
}

function textOf(children: unknown): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(textOf).join("");
  if (children && typeof children === "object" && "props" in (children as never)) {
    return textOf((children as { props: { children: unknown } }).props.children);
  }
  return "";
}

export default function Markdown({ source, onNavigate, anchors = false }: Props) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props) {
            const { className, children, ...rest } = props;
            const text = String(children).replace(/\n$/, "");
            if (/language-mermaid/.test(className ?? "")) {
              return <Mermaid chart={text} />;
            }
            const isBlock = (className ?? "").startsWith("language-");
            if (!isBlock) {
              return (
                <code className="inline-code" {...rest}>
                  {children}
                </code>
              );
            }
            const lang = (className ?? "").replace("language-", "");
            return (
              <div className="code-block">
                {lang && <span className="code-lang">{lang}</span>}
                <pre>
                  <code className={className}>{text}</code>
                </pre>
              </div>
            );
          },
          a(props) {
            const href = props.href ?? "";
            if (href.startsWith("/")) {
              return (
                <a
                  href={href}
                  onClick={(e) => {
                    e.preventDefault();
                    onNavigate(href);
                  }}
                >
                  {props.children}
                </a>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {props.children}
              </a>
            );
          },
          h2(props) {
            return anchors ? (
              <h2 id={headingId(textOf(props.children))}>{props.children}</h2>
            ) : (
              <h2>{props.children}</h2>
            );
          },
          table(props) {
            return (
              <div className="table-wrap">
                <table>{props.children}</table>
              </div>
            );
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
