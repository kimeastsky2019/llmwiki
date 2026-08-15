import { useEffect, useMemo, useRef, useState } from "react";
import { api, type SourceContent, type SourceFile, type SourceRoot } from "./api";
import { HIGHLIGHT_LIMIT, highlightLines, langFromPath, type Token } from "./highlight";
import { useLang } from "./i18n";

export interface SourceTarget {
  path: string;
  root?: number;
  line?: number;
}

interface Props {
  target: SourceTarget | null;
  onClose: () => void;
}

/** 컴팩트 트리 노드 — 자식이 하나뿐인 디렉터리는 한 줄로 접는다 (com/gng/inst 처럼). */
interface DirNode {
  name: string;
  key: string;
  dirs: DirNode[];
  files: SourceFile[];
}

export default function SourceBrowser({ target, onClose }: Props) {
  const { t } = useLang();
  const [roots, setRoots] = useState<SourceRoot[] | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<SourceTarget | null>(target);
  const [content, setContent] = useState<SourceContent | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.sourceTree().then(setRoots).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    if (target) setSelected(target);
  }, [target]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!selected) {
      setContent(null);
      return;
    }
    let live = true;
    setContent(null);
    setErr(null);
    api
      .source(selected.path, selected.root)
      .then((r) => live && setContent(r))
      .catch((e) => live && setErr(e.message));
    return () => {
      live = false;
    };
  }, [selected?.path, selected?.root]);

  // 파일 수가 적으면 전부 펼쳐 두는 편이 빠르다. 큰 저장소는 최상위만.
  useEffect(() => {
    if (!roots) return;
    const total = roots.reduce((n, r) => n + r.files.length, 0);
    if (total > 300) return;
    const keys = new Set<string>();
    const walk = (node: DirNode) => {
      keys.add(node.key);
      node.dirs.forEach(walk);
    };
    roots.forEach((r) => buildTree(r).dirs.forEach(walk));
    setExpanded(keys);
  }, [roots]);

  return (
    <div className="sb-backdrop" onClick={onClose}>
      <div className="sb-panel" onClick={(e) => e.stopPropagation()}>
        <header className="sb-head">
          <strong>{t("sourceBrowser")}</strong>
          <button className="sb-close" onClick={onClose} title={t("close")}>
            ✕
          </button>
        </header>

        <div className="sb-body">
          <div className="sb-tree">
            <input
              className="sb-filter"
              placeholder={t("filterFiles")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              autoFocus
            />
            <div className="sb-tree-scroll">
              {roots === null && <div className="sb-muted">{t("loading")}</div>}
              {roots?.map((root) => (
                <RootTree
                  key={root.index}
                  root={root}
                  filter={filter}
                  expanded={expanded}
                  onToggle={(key) =>
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(key)) next.delete(key);
                      else next.add(key);
                      return next;
                    })
                  }
                  selected={selected}
                  onPick={(path) => setSelected({ path, root: root.index })}
                  showRootName={(roots?.length ?? 0) > 1}
                />
              ))}
            </div>
          </div>

          <div className="sb-view">
            {err && <div className="sb-error">{err}</div>}
            {!err && !selected && <div className="sb-muted pad">{t("pickFile")}</div>}
            {!err && selected && !content && <div className="sb-muted pad">{t("loading")}</div>}
            {!err && content && <CodeView file={content} jumpTo={selected?.line} />}
          </div>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
function buildTree(root: SourceRoot): DirNode {
  const rootNode: DirNode = { name: root.name, key: `${root.index}:`, dirs: [], files: [] };
  const index = new Map<string, DirNode>([["", rootNode]]);

  for (const file of root.files) {
    const parts = file.path.split("/");
    const dirParts = parts.slice(0, -1);
    let prefix = "";
    let parent = rootNode;
    for (const part of dirParts) {
      prefix = prefix ? `${prefix}/${part}` : part;
      let node = index.get(prefix);
      if (!node) {
        node = { name: part, key: `${root.index}:${prefix}`, dirs: [], files: [] };
        index.set(prefix, node);
        parent.dirs.push(node);
      }
      parent = node;
    }
    parent.files.push(file);
  }
  return compact(rootNode);
}

/** 자식 디렉터리 하나만 있고 파일이 없는 노드를 위 노드에 합친다. */
function compact(node: DirNode): DirNode {
  node.dirs = node.dirs.map(compact);
  node.dirs.sort((a, b) => a.name.localeCompare(b.name));
  node.files.sort((a, b) => a.path.localeCompare(b.path));
  while (node.dirs.length === 1 && node.files.length === 0) {
    const only = node.dirs[0];
    node = {
      name: `${node.name}/${only.name}`,
      key: only.key,
      dirs: only.dirs,
      files: only.files,
    };
  }
  return node;
}

function filterTree(node: DirNode, needle: string): DirNode | null {
  const dirs = node.dirs.map((d) => filterTree(d, needle)).filter((d): d is DirNode => !!d);
  const files = node.files.filter((f) => f.path.toLowerCase().includes(needle));
  if (dirs.length === 0 && files.length === 0) return null;
  return { ...node, dirs, files };
}

function RootTree({
  root,
  filter,
  expanded,
  onToggle,
  selected,
  onPick,
  showRootName,
}: {
  root: SourceRoot;
  filter: string;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  selected: SourceTarget | null;
  onPick: (path: string) => void;
  showRootName: boolean;
}) {
  const { t } = useLang();
  const needle = filter.trim().toLowerCase();
  const tree = useMemo(() => buildTree(root), [root]);
  const shown = useMemo(
    () => (needle ? filterTree(tree, needle) : tree),
    [tree, needle]
  );

  if (root.files.length === 0) return <div className="sb-muted pad">{t("noFiles")}</div>;
  if (!shown) return <div className="sb-muted pad">{t("noMatch")}</div>;

  const isActive = (path: string) =>
    selected?.path === path && (selected.root ?? root.index) === root.index;

  return (
    <div className="sb-root">
      {showRootName && <div className="sb-root-name">{root.name}</div>}
      <DirRows
        node={shown}
        depth={0}
        // 검색 중에는 결과가 바로 보여야 하므로 접힘 상태를 무시한다
        forceOpen={!!needle}
        expanded={expanded}
        onToggle={onToggle}
        isActive={isActive}
        onPick={onPick}
      />
    </div>
  );
}

function DirRows({
  node,
  depth,
  forceOpen,
  expanded,
  onToggle,
  isActive,
  onPick,
}: {
  node: DirNode;
  depth: number;
  forceOpen: boolean;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  isActive: (path: string) => boolean;
  onPick: (path: string) => void;
}) {
  return (
    <>
      {node.dirs.map((dir) => {
        const open = forceOpen || expanded.has(dir.key);
        return (
          <div key={dir.key}>
            <button
              className="sb-dir"
              style={{ paddingLeft: 8 + depth * 12 }}
              onClick={() => onToggle(dir.key)}
            >
              <span className="sb-caret">{open ? "▾" : "▸"}</span>
              {dir.name}
            </button>
            {open && (
              <DirRows
                node={dir}
                depth={depth + 1}
                forceOpen={forceOpen}
                expanded={expanded}
                onToggle={onToggle}
                isActive={isActive}
                onPick={onPick}
              />
            )}
          </div>
        );
      })}
      {node.files.map((file) => (
        <button
          key={file.path}
          className={`sb-file ${isActive(file.path) ? "active" : ""}`}
          style={{ paddingLeft: 8 + depth * 12 + 14 }}
          onClick={() => onPick(file.path)}
          title={file.path}
        >
          <span className="sb-file-name">{file.path.split("/").pop()}</span>
          {file.parsed && <span className="sb-dot" />}
        </button>
      ))}
    </>
  );
}

// --------------------------------------------------------------------------- //
function CodeView({ file, jumpTo }: { file: SourceContent; jumpTo?: number }) {
  const { t } = useLang();
  const [find, setFind] = useState("");
  const [cursor, setCursor] = useState(0);
  const [copied, setCopied] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  const lang = file.lang && file.lang !== "text" ? file.lang : langFromPath(file.path);
  const tooBig = file.content.length > HIGHLIGHT_LIMIT;
  const lines = useMemo<Token[][]>(
    () =>
      tooBig
        ? file.content.split("\n").map((line) => [{ text: line }])
        : highlightLines(file.content, lang),
    [file.content, lang, tooBig]
  );

  const matches = useMemo(() => {
    const needle = find.trim().toLowerCase();
    if (needle.length < 2) return [];
    const hits: number[] = [];
    file.content.split("\n").forEach((line, i) => {
      if (line.toLowerCase().includes(needle)) hits.push(i + 1);
    });
    return hits;
  }, [find, file.content]);

  useEffect(() => setCursor(0), [find, file.path]);

  const scrollToLine = (line: number) => {
    const el = scroller.current?.querySelector(`[data-line="${line}"]`);
    el?.scrollIntoView({ block: "center" });
  };

  useEffect(() => {
    if (matches.length > 0) scrollToLine(matches[Math.min(cursor, matches.length - 1)]);
  }, [matches, cursor]);

  useEffect(() => {
    if (jumpTo) scrollToLine(jumpTo);
  }, [jumpTo, file.path]);

  const step = (delta: number) => {
    if (matches.length === 0) return;
    setCursor((c) => (c + delta + matches.length) % matches.length);
  };

  const activeLine = matches.length ? matches[Math.min(cursor, matches.length - 1)] : jumpTo;
  const hitLines = useMemo(() => new Set(matches), [matches]);

  return (
    <div className="sb-code">
      <div className="sb-code-head">
        <code className="sb-path">{file.path}</code>
        <span className="sb-meta">{t("lines", { n: file.lines })}</span>
        <button
          className="sb-mini"
          onClick={() => {
            navigator.clipboard?.writeText(file.path).then(
              () => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1200);
              },
              () => undefined
            );
          }}
        >
          {copied ? t("copied") : t("copyPath")}
        </button>
        <div className="sb-find">
          <input
            placeholder={t("findInFile")}
            value={find}
            onChange={(e) => setFind(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") step(e.shiftKey ? -1 : 1);
            }}
          />
          {find.trim().length >= 2 && (
            <>
              <span className="sb-meta">{t("matches", { n: matches.length })}</span>
              <button className="sb-mini" onClick={() => step(-1)} disabled={!matches.length}>
                {t("prevMatch")}
              </button>
              <button className="sb-mini" onClick={() => step(1)} disabled={!matches.length}>
                {t("nextMatch")}
              </button>
            </>
          )}
        </div>
      </div>

      {tooBig && <div className="sb-note">{t("highlightOff")}</div>}

      <div className="sb-code-scroll" ref={scroller}>
        <table className="sb-lines">
          <tbody>
            {lines.map((tokens, i) => {
              const no = i + 1;
              return (
                <tr
                  key={no}
                  data-line={no}
                  className={`${hitLines.has(no) ? "hit" : ""} ${no === activeLine ? "cur" : ""}`}
                >
                  <td className="sb-no">{no}</td>
                  <td className="sb-src">
                    {tokens.length === 0 ? (
                      " "
                    ) : (
                      tokens.map((tok, k) =>
                        tok.cls ? (
                          <span key={k} className={`hl-${tok.cls}`}>
                            {tok.text}
                          </span>
                        ) : (
                          <span key={k}>{tok.text}</span>
                        )
                      )
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
