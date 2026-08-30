"""에너지 진단 LLM Wiki — 데이터 컨트랙트가 걸린 위키 계층.

`llmwiki/kb/` 가 PDF 를 4채널로 갈라 그래프로 만드는 곳(L1·L2)이라면, 여기는 그
결과를 **사람이 읽고 고칠 수 있는 마크다운 위키**로 세우는 곳(L3 이후)이다.

    L0 원본 PDF → L1 파싱(kb) → L2 데이터 컨트랙트 → L3 위키 → L4 검색 → L5 서비스
"""

from . import calc, contract, units  # noqa: F401

__all__ = ["calc", "contract", "units"]
