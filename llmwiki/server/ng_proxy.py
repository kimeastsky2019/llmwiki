"""나노그리드 Knowledge Wiki 프록시.

llmwiki 포털에서 /api/ng/* 요청을 ngwiki wiki-server(기본 8720)로 넘긴다.
웹 SPA는 llmwiki 서버 하나만 바라보므로 CORS·인증이 일원화된다.

환경변수 NGWIKI_API 로 대상 주소를 바꾼다 (docker 에선 http://wiki-server:8720).
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException, Request

NGWIKI_API = os.environ.get("NGWIKI_API", "http://127.0.0.1:8720").rstrip("/")
TIMEOUT = httpx.Timeout(120.0, connect=5.0)  # 예측 학습 요청이 섞이므로 넉넉히

router = APIRouter()


@router.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request):
    url = f"{NGWIKI_API}/api/ng/{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if request.method == "GET":
                resp = await client.get(url, params=dict(request.query_params))
            else:
                resp = await client.post(
                    url,
                    content=await request.body(),
                    headers={"content-type": "application/json"},
                )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"나노그리드 지식위키 서버 연결 실패({NGWIKI_API}): {e}") from e
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()
