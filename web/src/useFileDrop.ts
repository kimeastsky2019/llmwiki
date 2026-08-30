import { useCallback, useEffect, useRef, useState } from "react";

/** 파일 끌어다 놓기 — 화면 두 곳(지식 데이터베이스 · 위키 관리자)이 같은 규칙을 쓴다.
 *
 * 두 가지를 조심한다.
 *
 * 1. **빗나간 드롭이 화면을 날린다.** 브라우저 기본 동작은 놓인 파일을 그 탭에서 여는
 *    것이라, 드롭 영역을 살짝 벗어나면 SPA 가 통째로 PDF 뷰어로 바뀌고 입력하던
 *    업종·검토자가 사라진다. 그래서 창 전체에서 기본 동작을 막는다.
 * 2. **받지 않는 형식은 그 자리에서 말한다.** 조용히 받아 두면 '분석하기' 를 누른 뒤에야
 *    서버가 400 을 주는데, 그때는 사용자가 무엇을 잘못했는지 모른다.
 */
export function useFileDrop({
  accept,
  onFile,
  onReject,
  disabled = false,
}: {
  /** 허용 확장자 목록. 원본은 서버(`parser_ready.formats.suffixes`)다. */
  accept: string;
  onFile: (file: File) => void;
  onReject: (message: string) => void;
  disabled?: boolean;
}) {
  const [isOver, setIsOver] = useState(false);
  // dragenter/leave 는 자식 위를 지날 때마다 번갈아 오므로 깊이를 센다.
  // 세지 않으면 아이콘 위를 지날 때 테두리가 깜빡인다.
  const depth = useRef(0);

  useEffect(() => {
    const swallow = (e: DragEvent) => {
      // 드롭 영역 밖이면 아무 일도 일어나지 않아야 한다 — 파일이 열리면 안 된다.
      e.preventDefault();
    };
    addEventListener("dragover", swallow);
    addEventListener("drop", swallow);
    return () => {
      removeEventListener("dragover", swallow);
      removeEventListener("drop", swallow);
    };
  }, []);

  const suffixes = accept
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter((s) => s.startsWith("."));

  const take = useCallback(
    (files: FileList | null) => {
      const list = Array.from(files ?? []);
      if (list.length === 0) return;
      const file = list[0];
      const dot = file.name.lastIndexOf(".");
      const suffix = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
      if (suffixes.length > 0 && !suffixes.includes(suffix)) {
        onReject(`${suffix || file.name} · ${suffixes.join(" ")}`);
        return;
      }
      onFile(file);
      // 여러 개를 놓은 경우: 분석은 문서 단위라 첫 건만 쓴다. 조용히 버리지 않는다.
      if (list.length > 1) onReject(`${list.length}:${file.name}`);
    },
    [suffixes.join(","), onFile, onReject]
  );

  const dropProps = {
    onDragEnter: (e: React.DragEvent) => {
      if (disabled) return;
      e.preventDefault();
      depth.current += 1;
      setIsOver(true);
    },
    onDragOver: (e: React.DragEvent) => {
      if (disabled) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (e: React.DragEvent) => {
      if (disabled) return;
      e.preventDefault();
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setIsOver(false);
    },
    onDrop: (e: React.DragEvent) => {
      if (disabled) return;
      e.preventDefault();
      depth.current = 0;
      setIsOver(false);
      take(e.dataTransfer.files);
    },
  };

  return { isOver, dropProps };
}
