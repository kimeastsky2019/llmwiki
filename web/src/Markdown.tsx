import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Mermaid from "./Mermaid";

interface Props {
  source: string;
  onNavigate: (path: string) => void;
}

export default function Markdown({ source, onNavigate }: Props) {
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
