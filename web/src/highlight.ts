/** 의존성 없는 최소 구문 강조.
 *
 * 망분리 환경 반입을 전제로 하므로 외부 하이라이터를 추가하지 않는다.
 * 완벽한 파싱이 목적이 아니라 '읽을 때 눈에 들어오게' 하는 것이 목적이다.
 */

export type Token = { text: string; cls?: string };

/** 이 크기를 넘으면 강조를 포기하고 평문으로 넘긴다 (브라우저가 멈추지 않도록). */
export const HIGHLIGHT_LIMIT = 200_000;

const JAVA_KEYWORDS =
  "abstract|assert|boolean|break|byte|case|catch|char|class|const|continue|default|do|double|else|enum|extends|final|finally|float|for|goto|if|implements|import|instanceof|int|interface|long|native|new|package|private|protected|public|return|short|static|strictfp|super|switch|synchronized|this|throw|throws|transient|try|void|volatile|while|true|false|null|var|record|sealed|yield";

const SQL_KEYWORDS =
  "select|insert|update|delete|merge|from|where|and|or|not|in|exists|between|like|is|null|order|group|by|having|join|inner|left|right|outer|full|on|as|union|all|distinct|into|values|set|case|when|then|else|end|with|limit|offset|asc|desc|count|sum|avg|min|max|nvl|decode|to_char|to_date|sysdate|dual|create|table|alter|drop|index|view|commit|rollback";

interface Rule {
  cls: string;
  re: string;
  flags?: string;
}

const RULES: Record<string, Rule[]> = {
  java: [
    { cls: "cmt", re: "//[^\\n]*|/\\*[\\s\\S]*?\\*/" },
    { cls: "str", re: '"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'' },
    { cls: "ann", re: "@[A-Za-z_$][\\w$]*" },
    { cls: "kw", re: `\\b(?:${JAVA_KEYWORDS})\\b` },
    { cls: "num", re: "\\b\\d[\\d_]*(?:\\.[\\d_]+)?[fFdDlL]?\\b" },
    { cls: "typ", re: "\\b[A-Z][A-Za-z0-9_$]*\\b" },
  ],
  xml: [
    { cls: "cmt", re: "<!--[\\s\\S]*?-->" },
    { cls: "cdata", re: "<!\\[CDATA\\[[\\s\\S]*?\\]\\]>" },
    { cls: "tag", re: "</?[A-Za-z_][\\w:.-]*|/?>" },
    { cls: "str", re: '"[^"]*"|\'[^\']*\'' },
    { cls: "attr", re: "[A-Za-z_][\\w:.-]*(?=\\s*=)" },
    { cls: "var", re: "[#$]\\{[^}]*\\}" },
  ],
  sql: [
    { cls: "cmt", re: "--[^\\n]*|/\\*[\\s\\S]*?\\*/" },
    { cls: "str", re: "'(?:''|[^'])*'" },
    { cls: "var", re: "[#$]\\{[^}]*\\}" },
    { cls: "kw", re: `\\b(?:${SQL_KEYWORDS})\\b`, flags: "i" },
    { cls: "num", re: "\\b\\d+(?:\\.\\d+)?\\b" },
  ],
  properties: [
    { cls: "cmt", re: "^[#!][^\\n]*" },
    { cls: "attr", re: "^[\\w.$-]+(?=\\s*[=:])" },
  ],
  yaml: [
    { cls: "cmt", re: "#[^\\n]*" },
    { cls: "attr", re: "^\\s*[\\w.$-]+(?=\\s*:)" },
    { cls: "str", re: '"[^"]*"|\'[^\']*\'' },
  ],
  json: [
    { cls: "attr", re: '"[^"]*"(?=\\s*:)' },
    { cls: "str", re: '"(?:\\\\.|[^"\\\\])*"' },
    { cls: "num", re: "-?\\b\\d+(?:\\.\\d+)?\\b" },
    { cls: "kw", re: "\\b(?:true|false|null)\\b" },
  ],
  js: [
    { cls: "cmt", re: "//[^\\n]*|/\\*[\\s\\S]*?\\*/" },
    { cls: "str", re: '"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'|`(?:\\\\.|[^`\\\\])*`' },
    {
      cls: "kw",
      re: "\\b(?:const|let|var|function|return|if|else|for|while|import|export|from|default|class|new|await|async|try|catch|finally|throw|typeof|interface|type|true|false|null|undefined)\\b",
    },
    { cls: "num", re: "\\b\\d+(?:\\.\\d+)?\\b" },
  ],
  css: [
    { cls: "cmt", re: "/\\*[\\s\\S]*?\\*/" },
    { cls: "str", re: '"[^"]*"|\'[^\']*\'' },
    { cls: "attr", re: "[-\\w]+(?=\\s*:)" },
    { cls: "num", re: "#[0-9a-fA-F]{3,8}\\b|\\b\\d+(?:\\.\\d+)?(?:px|em|rem|%|vh|vw|s|ms)?\\b" },
  ],
};

const compiled = new Map<string, { re: RegExp; classes: string[] } | null>();

function grammar(lang: string) {
  if (compiled.has(lang)) return compiled.get(lang)!;
  const rules = RULES[lang];
  if (!rules) {
    compiled.set(lang, null);
    return null;
  }
  // 규칙마다 캡처 그룹 1개로 감싸 어느 규칙이 맞았는지 인덱스로 식별한다.
  const flags = new Set(["g", "m"]);
  for (const r of rules) for (const f of r.flags ?? "") flags.add(f);
  const re = new RegExp(rules.map((r) => `(${r.re})`).join("|"), [...flags].join(""));
  const entry = { re, classes: rules.map((r) => r.cls) };
  compiled.set(lang, entry);
  return entry;
}

/** 텍스트 전체를 토큰으로 나눈다. 지원하지 않는 언어면 통짜 토큰 하나. */
export function tokenize(text: string, lang: string): Token[] {
  const g = grammar(lang);
  if (!g) return [{ text }];

  const out: Token[] = [];
  let last = 0;
  g.re.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = g.re.exec(text)) !== null) {
    // 빈 매치는 무한 루프를 만든다 — 한 칸 밀고 계속.
    if (m[0] === "") {
      g.re.lastIndex += 1;
      continue;
    }
    if (m.index > last) out.push({ text: text.slice(last, m.index) });
    const hit = g.classes.findIndex((_, i) => m![i + 1] !== undefined);
    out.push({ text: m[0], cls: hit >= 0 ? g.classes[hit] : undefined });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

/**
 * 줄 단위 토큰. 여러 줄에 걸친 주석·문자열도 한 토큰으로 잡은 뒤 줄로 쪼개므로
 * 줄마다 따로 파싱할 때 생기는 오작동이 없다.
 */
export function highlightLines(text: string, lang: string): Token[][] {
  const lines: Token[][] = [[]];
  for (const tok of tokenize(text, lang)) {
    const parts = tok.text.split("\n");
    parts.forEach((part, i) => {
      if (i > 0) lines.push([]);
      if (part) lines[lines.length - 1].push({ text: part, cls: tok.cls });
    });
  }
  return lines;
}

export function langFromPath(path: string): string {
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  const map: Record<string, string> = {
    ".java": "java",
    ".xml": "xml",
    ".jsp": "xml",
    ".html": "xml",
    ".htm": "xml",
    ".sql": "sql",
    ".properties": "properties",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".js": "js",
    ".ts": "js",
    ".tsx": "js",
    ".css": "css",
  };
  return map[ext] ?? "text";
}
