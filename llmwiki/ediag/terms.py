"""ID 용 용어 사전 — 한글 명칭을 ASCII 식별자로 옮긴다.

`stable_id` 를 ASCII 로 고정한 이유는 ID 가 파일명·URL·TTL·그래프 DB 키로 동시에
쓰이기 때문이다. 한글 ID 는 편집기에서는 잘 보이지만 인용 경로 어딘가에서 반드시
깨진다 — 그리고 ID 가 깨지면 링크 전체가 끊긴다.

사전에 없는 명칭은 **번역을 지어내지 않는다.** 짧은 해시로 ID 를 만들고
``needs_naming`` 을 남겨 사람이 이름을 붙이게 한다. 지어낸 번역은 같은 설비가
보고서마다 다른 ID 를 받게 만들어, ECM 재사용이라는 목적 자체를 무너뜨린다.
"""

from __future__ import annotations

import hashlib
import re

#: 설비·공정 용어. 긴 것부터 본다 ('노통연관보일러' 가 '보일러' 로 잘리면 안 된다).
EQUIPMENT_TERMS: tuple[tuple[str, str], ...] = (
    ("노통연관", "flue-smoke-tube-boiler"),
    ("관류보일러", "once-through-boiler"),
    ("증기보일러", "steam-boiler"),
    ("폐열보일러", "waste-heat-boiler"),
    ("루츠블로워", "roots-blower"),
    ("루츠부로워", "roots-blower"),
    ("디스크건조기", "disc-dryer"),
    ("회전식디스크", "rotary-disc-dryer"),
    ("건조기배기팬", "dryer-exhaust-fan"),
    ("삼상분리기", "tri-phase-separator"),
    ("냉각수순환펌프", "cooling-water-pump"),
    ("순환펌프", "circulation-pump"),
    ("이송콘베어", "conveyor"),
    ("이송컨베이어", "conveyor"),
    ("탈수기", "dewaterer"),
    ("분쇄기", "crusher"),
    ("파쇄기", "shredder"),
    ("선별기", "sorter"),
    ("냉각탑", "cooling-tower"),
    ("탈취", "deodorizer"),
    ("송풍기", "blower"),
    ("건조기", "dryer"),
    ("보일러", "boiler"),
    ("발효조", "fermenter"),
    ("공조기", "ahu"),
    ("냉동기", "chiller"),
    ("전동기", "motor"),
    ("인버터", "inverter"),
    ("압축기", "compressor"),
)

#: 설비가 아니라 **설치 위치**인 말. 여기 걸리면 설비명으로 올리지 않는다 —
#: 위키에 '건조실' 이라는 설비가 생기면 설비-개선안 연결이 통째로 어긋난다.
LOCATION_TERMS: tuple[str, ...] = (
    "숙성실", "건조실", "발효실", "기계실", "옥상", "지하", "전실", "동", "라인", "공정",
)


def is_location(name: str) -> bool:
    flat = re.sub(r"\s+", "", name or "")
    return any(term in flat for term in LOCATION_TERMS)


def ascii_term(name: str) -> tuple[str, bool]:
    """한글 명칭 → ASCII 조각. 두 번째 값이 True 면 사람이 이름을 붙여야 한다."""
    flat = re.sub(r"\s+", "", name or "")
    for ko, en in EQUIPMENT_TERMS:
        if ko in flat:
            return en, False
    ascii_only = re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-").lower()
    if ascii_only:
        return ascii_only[:32], False
    return "eq" + hashlib.sha256(flat.encode("utf-8")).hexdigest()[:6], True


#: 개선안(ECM) 카드의 닫힌 목록. 사업장이 달라도 **패턴이 반복**되므로 ID 는
#: 사업장에 매이지 않는다 — 그래야 다음 진단에서 같은 카드가 재사용된다.
MEASURE_CATALOG: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("디스크", "건조기"), "ecm-rotary-disc-dryer", "회전식 디스크 건조기 도입"),
    (("노통연관",), "ecm-waste-heat-recovery-boiler", "노통연관 폐열회수 보일러 도입"),
    (("폐열", "보일러"), "ecm-waste-heat-recovery-boiler", "노통연관 폐열회수 보일러 도입"),
    (("루츠블로워",), "ecm-roots-blower-replacement", "루츠블로워 개체"),
    (("부속설비",), "ecm-aux-equipment-efficiency", "부속설비 고효율 개체"),
    (("고효율", "전동기"), "ecm-high-efficiency-motor", "고효율 전동기 교체"),
    (("인버터",), "ecm-inverter-control", "인버터 제어 도입"),
    (("단열",), "ecm-insulation", "배관·설비 단열 보강"),
    (("절탄기",), "ecm-economizer", "절탄기(이코노마이저) 설치"),
    (("탈취",), "ecm-deodorizing-combustion", "탈취 연소로 개선"),
)


def match_measure(text: str) -> tuple[str, str] | None:
    """제목 문구에서 ECM 카드 유형을 찾는다. 못 찾으면 None — 지어내지 않는다."""
    flat = re.sub(r"\s+", "", text or "")
    for keys, mid, title in MEASURE_CATALOG:
        if all(k in flat for k in keys):
            return mid, title
    return None
