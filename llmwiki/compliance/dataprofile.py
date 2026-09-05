"""데이터 폴더 분석 — 유효성과 편향성을 **룰이 계산한다.**

회의에서 나온 자동화의 경계가 여기에도 그대로 적용된다. 모델이 "이 데이터는
편향됐다" 고 말하게 두면 같은 데이터에 다른 답이 나오고, 감독기관 앞에서
재현할 수 없다. 그래서 —

  · **수치는 전부 여기서 센다.** 결측률·고유값·집단 분포·집단 간 격차(DI).
    같은 파일이면 언제 돌려도 같은 값이 나온다.
  · **판정하지 않는다.** 임계치를 넘었다는 사실만 말하고 "위반" 이라 하지 않는다.
    32항목의 Yes/No 는 사람이 누른다 — 여기서 나오는 것은 전부 `candidate` 다.
  · **sLM 은 설명만 한다.** 이 모듈은 LLM 을 부르지 않는다. 화면이 필요하면
    `assist` 에 이 수치를 컨텍스트로 넘겨 말로 풀게 한다.

임계치는 여기서 정하지 않고 `risk_master.yaml` 의 `technical_thresholds` 에서
읽는다. 거기 `scored: false` 이고 출처가 '추정' 이라고 적혀 있는 값이라,
화면도 그 출처를 함께 보여 줘야 한다 — 근거 없는 숫자로 사람을 움직이면 안 된다.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import riskassess

#: 읽는 확장자. 열어 보지 못하는 것은 세지 않고 목록에만 남긴다.
READABLE = {".csv", ".tsv", ".xlsx", ".xlsm"}

#: 한 파일에서 읽을 최대 행. 폴더째 올리면 수백만 행이 올 수 있어 상한을 둔다.
#: 표본이라는 것을 결과에 적어 둔다 — 전수라고 오해하면 안 된다.
MAX_ROWS = 20000

#: 보호속성 후보. 이름으로 찾는 것이라 **확정이 아니라 후보다.**
#: 현장마다 컬럼명이 달라 여기 없는 것은 못 찾는다 — 화면이 직접 고를 수 있어야 한다.
PROTECTED_HINTS: dict[str, tuple[str, ...]] = {
    "성별": ("gender", "sex", "성별", "gndr"),
    "연령": ("age", "birth", "연령", "나이", "생년"),
    "지역": ("region", "area", "addr", "지역", "주소", "시도"),
    "국적": ("nation", "country", "국적", "외국인"),
    "장애": ("disab", "장애"),
    "직업": ("job", "occupation", "직업", "직군"),
}

#: 결과(라벨) 컬럼 후보. 있으면 집단별 승인율 격차를 잴 수 있다.
OUTCOME_HINTS = ("approve", "승인", "target", "label", "result", "판정", "yn", "여부", "score", "등급")

#: 결측률이 이보다 높으면 짚는다. RMF 에 규정된 값이 아니라 **운영 관행**이라
#: 출처를 함께 낸다.
MISSING_WARN = 0.20


@dataclass
class Column:
    name: str
    non_null: int = 0
    missing: int = 0
    unique: int = 0
    kind: str = "text"          # text | number | date
    top_value: str = ""
    top_ratio: float = 0.0

    @property
    def missing_ratio(self) -> float:
        total = self.non_null + self.missing
        return round(self.missing / total, 4) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "rows": self.non_null + self.missing,
            "missing": self.missing, "missing_ratio": self.missing_ratio,
            "unique": self.unique, "kind": self.kind,
            "top_value": self.top_value, "top_ratio": round(self.top_ratio, 4),
        }


@dataclass
class Dataset:
    name: str
    path: str
    rows: int = 0
    sampled: bool = False
    columns: list[Column] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "path": self.path, "rows": self.rows,
            "sampled": self.sampled, "error": self.error,
            "columns": [c.to_dict() for c in self.columns],
        }


def _kind(values: list[str]) -> str:
    sample = [v for v in values[:200] if v]
    if not sample:
        return "text"
    if all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in sample):
        return "number"
    if all(re.fullmatch(r"\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?", v) for v in sample):
        return "date"
    return "text"


def _read_rows(path: Path) -> tuple[list[str], list[list[str]], bool]:
    """머리글과 행. 못 읽으면 예외를 올린다."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        delim = "\t" if suffix == ".tsv" else ","
        raw = path.read_bytes()
        # 한글 CSV 는 cp949 로 저장되는 일이 흔하다. utf-8 로만 열면 통째로 깨진다.
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("인코딩을 알 수 없다 (utf-8·cp949 아님)")
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        rows = []
        head: list[str] = []
        for i, row in enumerate(reader):
            if i == 0:
                head = [c.strip() for c in row]
                continue
            if len(rows) >= MAX_ROWS:
                return head, rows, True
            rows.append(row)
        return head, rows, False

    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    head, rows, capped = [], [], False
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        cells = ["" if c is None else str(c).strip() for c in row]
        if i == 0:
            head = cells
            continue
        if len(rows) >= MAX_ROWS:
            capped = True
            break
        rows.append(cells)
    wb.close()
    return head, rows, capped


def profile_file(path: Path, *, root: Path | None = None) -> Dataset:
    rel = str(path.relative_to(root)) if root else path.name
    ds = Dataset(name=path.name, path=rel)
    try:
        head, rows, capped = _read_rows(path)
    except Exception as exc:  # noqa: BLE001 — 못 읽은 파일도 목록에는 남긴다
        ds.error = str(exc)[:200]
        return ds

    ds.rows = len(rows)
    ds.sampled = capped
    for idx, name in enumerate(head):
        col = Column(name=name or f"col{idx + 1}")
        seen: dict[str, int] = {}
        for row in rows:
            value = (row[idx] if idx < len(row) else "") or ""
            value = value.strip()
            if value == "":
                col.missing += 1
                continue
            col.non_null += 1
            seen[value] = seen.get(value, 0) + 1
        col.unique = len(seen)
        if seen:
            top, count = max(seen.items(), key=lambda kv: kv[1])
            col.top_value, col.top_ratio = top, count / max(col.non_null, 1)
        col.kind = _kind([r[idx] for r in rows[:200] if idx < len(r)])
        ds.columns.append(col)
    return ds


def _protected(name: str) -> str:
    low = name.lower()
    for label, hints in PROTECTED_HINTS.items():
        if any(h in low for h in hints):
            return label
    return ""


def _outcome_column(ds: Dataset) -> Column | None:
    """결과(라벨) 컬럼 후보. 이름으로 찾고, 값이 두세 종류인 것만 인정한다."""
    for col in ds.columns:
        low = col.name.lower()
        if any(h in low for h in OUTCOME_HINTS) and 2 <= col.unique <= 5:
            return col
    return None


def disparity(ds: Dataset, protected: Column, outcome: Column, rows: list[list[str]],
              head: list[str]) -> dict[str, Any] | None:
    """집단 간 격차 지수(DI) — 집단별 긍정 비율의 최소/최대.

    미국 EEOC 4/5 룰에서 온 관행값이고 RMF 규정이 아니다. 그래서 임계치와
    출처를 마스터에서 읽어 결과에 함께 실어 보낸다.
    """
    pi, oi = head.index(protected.name), head.index(outcome.name)
    positive = sorted({(r[oi] or "").strip() for r in rows if len(r) > oi and (r[oi] or "").strip()})
    if len(positive) < 2:
        return None
    # 값이 두 개면 사전순 뒤쪽을 '긍정' 으로 본다 (Y/N, 1/0, 승인/거절).
    good = positive[-1]

    groups: dict[str, list[int]] = {}
    for r in rows:
        if len(r) <= max(pi, oi):
            continue
        g = (r[pi] or "").strip()
        if not g:
            continue
        hit = groups.setdefault(g, [0, 0])
        hit[1] += 1
        if (r[oi] or "").strip() == good:
            hit[0] += 1

    # 표본이 너무 작은 집단은 비율이 튄다. 30건 미만은 계산에서 빼고 그 사실을 남긴다.
    usable = {g: v for g, v in groups.items() if v[1] >= 30}
    dropped = sorted(g for g, v in groups.items() if v[1] < 30)
    if len(usable) < 2:
        return None

    rates = {g: v[0] / v[1] for g, v in usable.items()}
    lo, hi = min(rates.values()), max(rates.values())
    di = round(lo / hi, 4) if hi > 0 else 0.0

    entry = next(
        (e for e in riskassess.master()["technical_thresholds"]["entries"]
         if "DI" in e["metric"]), {}
    )
    return {
        "protected": protected.name,
        "protected_kind": _protected(protected.name),
        "outcome": outcome.name,
        "positive_value": good,
        "groups": [
            {"value": g, "n": usable[g][1], "positive": usable[g][0],
             "rate": round(rates[g], 4)}
            for g in sorted(usable, key=lambda x: -rates[x])
        ],
        "dropped_small_groups": dropped,
        "di": di,
        # ★ 판정이 아니라 '임계치 밖' 이라는 사실만 말한다.
        "outside": not (0.8 <= di <= 1.25),
        "criterion": entry.get("criterion", ""),
        "source": entry.get("source", ""),
        "scored": riskassess.master()["technical_thresholds"]["scored"],
    }


def findings(datasets: list[Dataset], bias: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """수치 → 32항목 **후보**. codehints 와 같은 규약이다 — 전부 candidate."""
    out: list[dict[str, Any]] = []

    for ds in datasets:
        if ds.error:
            continue
        thin = [c for c in ds.columns if c.missing_ratio >= MISSING_WARN]
        if thin:
            out.append({
                "item_no": 7, "confidence": "candidate",
                "because": f"{ds.name} — 결측률 {int(MISSING_WARN * 100)}% 이상 컬럼 "
                           + ", ".join(f"{c.name} {int(c.missing_ratio * 100)}%" for c in thin[:4]),
                "source": "운영 관행 (RMF 규정값 아님)",
            })
        skewed = [c for c in ds.columns
                  if c.kind == "text" and c.unique > 1 and c.top_ratio >= 0.95]
        if skewed:
            out.append({
                "item_no": 8, "confidence": "candidate",
                "because": f"{ds.name} — 한 값이 95% 이상인 컬럼 "
                           + ", ".join(f"{c.name}({c.top_value})" for c in skewed[:4]),
                "source": "운영 관행 (RMF 규정값 아님)",
            })
        # 결측이 많아 이미 짚은 컬럼은 빼고 센다. 대부분이 비어 있는 자유기술
        # 컬럼은 남은 값이 같은 것이 당연해서, 그것까지 '오염' 으로 올리면
        # 후보 목록이 사람이 안 읽는 길이가 된다.
        thin_names = {c.name for c in thin}
        constant = [c for c in ds.columns
                    if c.non_null and c.unique == 1 and c.name not in thin_names]
        if constant:
            out.append({
                "item_no": 9, "confidence": "candidate",
                "because": f"{ds.name} — 값이 하나뿐인 컬럼 "
                           + ", ".join(c.name for c in constant[:4]),
                "source": "운영 관행 (RMF 규정값 아님)",
            })
        found = [c.name for c in ds.columns if _protected(c.name)]
        if found:
            out.append({
                "item_no": 32, "confidence": "candidate",
                "because": f"{ds.name} — 보호속성으로 보이는 컬럼 " + ", ".join(found[:5]),
                "source": "컬럼 이름 매칭 (확정 아님)",
            })

    for b in bias:
        if b["outside"]:
            out.append({
                "item_no": 10, "confidence": "candidate",
                "because": f"{b['protected']} 집단 간 격차 지수 DI={b['di']} "
                           f"({b['criterion']})",
                "source": b["source"],
            })
            out.append({
                "item_no": 11, "confidence": "candidate",
                "because": f"{b['outcome']} 결과가 {b['protected']} 집단별로 다르다 "
                           f"— 최저 {min(g['rate'] for g in b['groups'])} / "
                           f"최고 {max(g['rate'] for g in b['groups'])}",
                "source": b["source"],
            })

    labels = {i["no"]: f"{i['lv1']} > {i['lv3']}" for i in riskassess.items()}
    for f in out:
        f["label"] = labels.get(f["item_no"], "")
    return out


def analyze(folder: Path) -> dict[str, Any]:
    """폴더 하나를 통째로 분석한다. LLM 을 부르지 않는다."""
    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in READABLE
    )
    datasets = [profile_file(p, root=folder) for p in files]

    bias: list[dict[str, Any]] = []
    for ds, path in zip(datasets, files):
        if ds.error:
            continue
        outcome = _outcome_column(ds)
        if outcome is None:
            continue
        try:
            head, rows, _ = _read_rows(path)
        except Exception:  # noqa: BLE001
            continue
        for col in ds.columns:
            if not _protected(col.name) or col.unique < 2 or col.unique > 20:
                continue
            got = disparity(ds, col, outcome, rows, head)
            if got:
                bias.append({**got, "dataset": ds.name})

    return {
        "folder": folder.name,
        "datasets": [d.to_dict() for d in datasets],
        "bias": bias,
        "findings": findings(datasets, bias),
        "skipped": [p.name for p in folder.rglob("*")
                    if p.is_file() and p.suffix.lower() not in READABLE][:40],
        "max_rows": MAX_ROWS,
    }
