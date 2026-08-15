"""주석/문자열을 안전하게 제거(치환)하는 Java 텍스트 스캐너.

정규식만으로 Java를 파싱하면 주석 안의 중괄호나 문자열 안의 세미콜론에서
반드시 깨진다. 여기서 한 번 정리한 텍스트를 뒤에서 재사용한다.

- 줄 수는 원본과 동일하게 유지한다(라인 번호 보존).
- 문자열 리터럴은 \x00S{n}\x00 형태의 플레이스홀더로 치환하고 원문은 따로 보관한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PLACEHOLDER_RE = re.compile(r"\x00S(\d+)\x00")


@dataclass
class Scrubbed:
    text: str
    strings: list[str] = field(default_factory=list)

    def restore(self, s: str) -> str:
        return PLACEHOLDER_RE.sub(lambda m: self.strings[int(m.group(1))], s)

    def literals_in(self, s: str) -> list[str]:
        """따옴표를 벗긴 문자열 리터럴 목록."""
        return [
            self.strings[int(m.group(1))][1:-1] for m in PLACEHOLDER_RE.finditer(s)
        ]


def scrub(src: str) -> Scrubbed:
    out: list[str] = []
    strings: list[str] = []
    i, n = 0, len(src)

    while i < n:
        c = src[i]

        # 라인 주석
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
            continue

        # 블록 주석 (줄바꿈은 보존)
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            chunk = src[i:j]
            out.append("".join("\n" if ch == "\n" else " " for ch in chunk))
            i = j
            continue

        # 문자열 / 문자 리터럴
        if c in ('"', "'"):
            quote = c
            j = i + 1
            buf = []
            while j < n:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j : j + 2])
                    j += 2
                    continue
                if src[j] == quote:
                    j += 1
                    break
                if src[j] == "\n":  # 닫히지 않은 리터럴 — 방어
                    break
                buf.append(src[j])
                j += 1
            # 복원 시 원본 Java 로 되돌아가야 하므로 따옴표까지 함께 보관한다
            literal = quote + "".join(buf) + quote
            idx = len(strings)
            strings.append(literal)
            out.append(f"\x00S{idx}\x00")
            i = j
            continue

        out.append(c)
        i += 1

    return Scrubbed(text="".join(out), strings=strings)


def find_block(text: str, open_idx: int) -> int:
    """text[open_idx] == '{' 일 때 짝이 되는 '}' 의 인덱스를 반환. 없으면 -1."""
    if open_idx >= len(text) or text[open_idx] != "{":
        return -1
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1
