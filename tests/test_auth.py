"""로그인 — 확인은 서버가 하고, 비밀번호는 평문으로 남지 않는다.

화면에서만 통과시키면 주소를 아는 사람은 그대로 들어온다. 그래서 검사는
`/api/auth/login` 에 있고, 여기서 그 사실을 고정한다.

★ 이것은 **로그인**이지 **권한 검사가 아니다.** 들어온 뒤 각 API 가 "이 사람이
  이걸 해도 되나" 를 묻지 않는다는 것도 아래에 적어 둔다 — 없는 방어를 있다고
  믿지 않기 위해서다.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmwiki.compliance.seed import seed
from llmwiki.compliance.store import Store
from llmwiki.server import auth

CONFIG = """
project:
  name: "로그인 테스트"
  source_roots: ["{root}/sample"]
compliance:
  dir: "{data}"
  ruleset: "1.0.0"
  standard: "2026.08"
output:
  docs_dir: "{data}/docs"
  index_file: "{data}/docs/index.json"
"""

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("authroot")


# ── 저장 ──────────────────────────────────────────────────────────────────


def test_password_is_never_stored_in_the_clear(root):
    auth.add(root, user_id="kim", password=PASSWORD, role="admin", name="김동호")
    raw = auth.users_path(root).read_text(encoding="utf-8")
    assert PASSWORD not in raw
    stored = json.loads(raw)["users"]["kim"]["password"]
    assert stored["algo"] == "pbkdf2-sha256"
    assert int(stored["rounds"]) >= 200_000  # 낮추면 유출된 해시를 되짚기 쉬워진다


def test_same_password_gets_a_different_hash(root):
    a = auth.hash_password(PASSWORD)
    b = auth.hash_password(PASSWORD)
    # 솔트가 무작위라 두 해시가 다르다 — 같은 비밀번호를 쓰는 계정이 서로
    # 드러나지 않고, 미리 계산한 표로 한꺼번에 풀 수도 없다.
    assert a["salt"] != b["salt"]
    assert a["hash"] != b["hash"]


def test_short_password_is_refused(root):
    with pytest.raises(ValueError):
        auth.add(root, user_id="short", password="1234", role="admin")


def test_authenticate(root):
    assert auth.authenticate(root, "kim", PASSWORD) == {
        "id": "kim",
        "name": "김동호",
        "role": "admin",
    }
    assert auth.authenticate(root, "kim", PASSWORD + "!") is None
    assert auth.authenticate(root, "없는사람", PASSWORD) is None


def test_remove(root):
    auth.add(root, user_id="tmp", password=PASSWORD, role="governance")
    assert auth.remove(root, "tmp") is True
    assert auth.remove(root, "tmp") is False
    assert auth.authenticate(root, "tmp", PASSWORD) is None


def test_missing_file_is_not_an_error(tmp_path):
    # 계정 파일은 저장소에 없다(.gitignore). 없을 때 터지면 서버가 안 뜬다.
    assert auth.load(tmp_path) == {}
    assert auth.authenticate(tmp_path, "kim", PASSWORD) is None


# ── API ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("authapi")
    seed(Store(data))
    cfg_path = data / "config.yaml"
    cfg_path.write_text(
        CONFIG.format(root=Path(__file__).resolve().parents[1], data=data),
        encoding="utf-8",
    )
    auth.add(data, user_id="gngmeta", password=PASSWORD, role="admin", name="GnG Meta")

    import llmwiki.server.app as app_module

    previous = os.environ.get("LLMWIKI_CONFIG")
    os.environ["LLMWIKI_CONFIG"] = str(cfg_path)
    importlib.reload(app_module)
    try:
        with TestClient(app_module.app) as c:
            yield c
    finally:
        if previous is None:
            os.environ.pop("LLMWIKI_CONFIG", None)
        else:
            os.environ["LLMWIKI_CONFIG"] = previous
        importlib.reload(app_module)


def test_login_ok(client):
    got = client.post("/api/auth/login", json={"id": "gngmeta", "password": PASSWORD})
    assert got.status_code == 200
    assert got.json() == {"id": "gngmeta", "name": "GnG Meta", "role": "admin"}
    # 해시는 절대 화면 쪽으로 나가지 않는다.
    assert "password" not in got.text and "salt" not in got.text


def test_login_rejects_wrong_password(client):
    assert client.post(
        "/api/auth/login", json={"id": "gngmeta", "password": "틀린비밀번호"}
    ).status_code == 401


def test_login_does_not_reveal_which_part_was_wrong(client):
    """없는 아이디와 틀린 비밀번호가 같은 답을 낸다.

    다르게 답하면 아이디 목록부터 만들 수 있다 — 남은 것은 비밀번호뿐이 된다.
    """
    unknown = client.post("/api/auth/login", json={"id": "없는사람", "password": PASSWORD})
    wrong = client.post("/api/auth/login", json={"id": "gngmeta", "password": "틀림"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_login_needs_both_fields(client):
    assert client.post("/api/auth/login", json={"id": "gngmeta"}).status_code == 400
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 400


def test_login_is_not_authorization(client):
    """로그인은 문을 열 뿐, 그 뒤 API 는 누구인지 묻지 않는다.

    이건 결함이 아니라 **아직 없는 것**이다(인사 테이블·SSO 가 붙어야 한다).
    화면에도 그렇게 적어 두었고, 여기서도 고정해 둔다 — 나중에 권한 검사가
    생기면 이 테스트가 먼저 깨져서 화면 문구를 같이 고치게 된다.
    """
    assert client.get("/api/reg/graph").status_code == 200
