"""계정 — 아이디·비밀번호를 **서버가** 확인한다.

회의에서 정해진 최종 모습은 SSO 다("SSO 로 다 처리할 겁니다"). 이 모듈은 그
전까지 쓰는 것이고, SSO 가 붙으면 통째로 빠진다.

그래도 화면에서만 통과시키지는 않는다. 화면 검사는 검사가 아니다 — 주소를
아는 사람은 그대로 들어온다. 그래서 확인은 서버에서 하고, 비밀번호는 평문으로
두지 않는다.

  · **해시로만 저장한다.** PBKDF2-HMAC-SHA256, 무작위 솔트, 200,000회.
    파일이 새어도 비밀번호 자체는 나오지 않는다.
  · **저장소에 넣지 않는다.** 계정 파일은 `.gitignore` 에 있고, 서버에서
    `llmwiki auth add` 로 만든다. 이 저장소는 공개다.
  · **비교는 상수 시간으로 한다.** `compare_digest` — 다르다는 것을 언제
    알아채는지로 비밀번호를 한 글자씩 맞춰 나갈 수 없게 한다.

★ 이것은 **로그인**이지 **권한 검사가 아니다.** 들어온 뒤 각 API 가 "이 사람이
  이걸 해도 되나" 를 묻지 않는다. 그건 인사 테이블·조직도가 붙어야 할 수 있는
  일이라, 지금은 없다는 것을 화면과 여기에 적어 둔다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

#: 계정 파일. 환경변수로 옮길 수 있게 두되 기본값은 설정 디렉터리 옆이다.
USERS_FILE = "auth_users.json"

#: 반복 횟수. 낮추지 말 것 — 낮추면 유출된 해시를 되짚기 쉬워진다.
ROUNDS = 200_000


def users_path(root: Path) -> Path:
    return Path(os.environ.get("LLMWIKI_USERS", root / USERS_FILE))


def hash_password(password: str, *, salt: bytes | None = None) -> dict[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS)
    return {
        "algo": "pbkdf2-sha256",
        "rounds": str(ROUNDS),
        "salt": salt.hex(),
        "hash": digest.hex(),
    }


def _verify(stored: dict[str, Any], password: str) -> bool:
    try:
        salt = bytes.fromhex(str(stored["salt"]))
        rounds = int(stored.get("rounds", ROUNDS))
    except (KeyError, ValueError):
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    # 상수 시간 비교. `==` 는 앞에서부터 달라지는 순간 끝나서 시간이 새어 나간다.
    return hmac.compare_digest(got.hex(), str(stored.get("hash", "")))


def load(root: Path) -> dict[str, dict[str, Any]]:
    path = users_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data.get("users", {}) if isinstance(data, dict) else {}


def save(root: Path, users: dict[str, dict[str, Any]]) -> Path:
    path = users_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"users": users}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 계정 파일은 남이 읽을 이유가 없다.
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - 파일시스템이 막을 수 있다
        pass
    return path


def add(root: Path, *, user_id: str, password: str, role: str, name: str = "") -> dict[str, Any]:
    uid = user_id.strip()
    if not uid:
        raise ValueError("아이디가 필요하다")
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 한다")
    users = load(root)
    users[uid] = {
        "name": name.strip() or uid,
        "role": role,
        "password": hash_password(password),
    }
    save(root, users)
    return {"id": uid, "name": users[uid]["name"], "role": role}


def remove(root: Path, user_id: str) -> bool:
    users = load(root)
    if user_id not in users:
        return False
    del users[user_id]
    save(root, users)
    return True


def authenticate(root: Path, user_id: str, password: str) -> dict[str, Any] | None:
    """맞으면 사람과 역할을, 틀리면 None.

    아이디가 없을 때도 해시 한 번을 돌린다 — 없는 아이디만 빨리 실패하면
    응답 시간으로 어떤 아이디가 있는지 알아낼 수 있다.
    """
    users = load(root)
    found = users.get(user_id.strip())
    if found is None:
        hash_password(password)  # 시간 맞추기용. 결과는 쓰지 않는다.
        return None
    if not _verify(found.get("password", {}), password):
        return None
    return {"id": user_id.strip(), "name": found.get("name", user_id), "role": found.get("role", "")}
