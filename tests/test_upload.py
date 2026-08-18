"""브라우저 업로드 — 경로 방어와 한도."""

from __future__ import annotations

import importlib
import io
import os
import time
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from llmwiki.server.upload import (
    MAX_FILE_BYTES,
    Incoming,
    UploadError,
    extract_zip,
    safe_relpath,
    store_files,
    strip_common_root,
    unique_dir,
)


# --------------------------------------------------------------------------- #
# 경로 정규화
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        "../../etc/passwd",
        "a/../../b.java",
        "/etc/passwd",  # 절대경로는 앞이 벗겨져 etc/passwd 로 남는다 (밖으로 못 나감)
        "",
        ".git/config",
        "src/.env",
        "node_modules/x/a.js",
        "target/classes/A.java",
    ],
)
def test_safe_relpath_rejects_or_contains(raw):
    out = safe_relpath(raw)
    # 통과했다면 최소한 상위로 올라가지는 않아야 한다
    assert out is None or ".." not in out.split("/")


def test_safe_relpath_normalizes_windows_and_drive():
    assert safe_relpath(r"C:\src\main\A.java") == "src/main/A.java"
    assert safe_relpath("proj//src///A.java") == "proj/src/A.java"


def test_safe_relpath_keeps_plain_path():
    assert safe_relpath("proj/src/main/java/A.java") == "proj/src/main/java/A.java"


def test_strip_common_root():
    assert strip_common_root(["p/a.java", "p/b/c.java"]) == ["a.java", "b/c.java"]
    # 최상위가 갈리면 벗기지 않는다
    assert strip_common_root(["p/a.java", "q/b.java"]) == ["p/a.java", "q/b.java"]
    # 벗기면 이름이 사라지는 경우도 그대로 둔다
    assert strip_common_root(["a.java"]) == ["a.java"]


# --------------------------------------------------------------------------- #
# 폴더 업로드
# --------------------------------------------------------------------------- #
def _incoming(rel: str, body: bytes = b"class A {}") -> Incoming:
    return Incoming(rel=rel, stream=io.BytesIO(body))


def test_store_files_writes_and_strips_root(tmp_path):
    dest = tmp_path / "proj"
    stats = store_files(
        dest,
        [_incoming("myproj/src/A.java"), _incoming("myproj/conf/x.xml", b"<x/>")],
    )
    assert stats.files == 2
    assert (dest / "src" / "A.java").read_text() == "class A {}"
    assert (dest / "conf" / "x.xml").read_text() == "<x/>"


def test_store_files_blocks_traversal(tmp_path):
    dest = tmp_path / "proj"
    stats = store_files(
        dest, [_incoming("ok/A.java"), _incoming("ok/../../../evil.java")]
    )
    assert stats.files == 1
    assert stats.skipped == 1
    assert not (tmp_path.parent / "evil.java").exists()
    assert not (tmp_path / "evil.java").exists()


def test_store_files_filters_extensions(tmp_path):
    dest = tmp_path / "proj"
    stats = store_files(
        dest, [_incoming("p/A.java"), _incoming("p/lib.jar", b"\x00\x01")]
    )
    assert stats.files == 1
    assert stats.skipped == 1
    assert not (dest / "lib.jar").exists()


def test_store_files_rejects_when_nothing_usable(tmp_path):
    with pytest.raises(UploadError):
        store_files(tmp_path / "proj", [_incoming("p/a.jar"), _incoming("p/b.class")])


def test_store_files_drops_oversized_file(tmp_path):
    dest = tmp_path / "proj"
    big = b"x" * (MAX_FILE_BYTES + 1024)
    stats = store_files(dest, [_incoming("p/A.java"), _incoming("p/Big.java", big)])
    assert stats.files == 1
    # 쓰다 만 파일이 남으면 안 된다
    assert not (dest / "Big.java").exists()
    assert stats.skipped == 1


# --------------------------------------------------------------------------- #
# ZIP 업로드
# --------------------------------------------------------------------------- #
def _zip(entries: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    buf.seek(0)
    return buf


def test_extract_zip_writes(tmp_path):
    dest = tmp_path / "proj"
    stats = extract_zip(dest, _zip({"p/src/A.java": b"class A {}", "p/m.xml": b"<m/>"}))
    assert stats.files == 2
    assert (dest / "src" / "A.java").read_text() == "class A {}"


def test_extract_zip_blocks_zip_slip(tmp_path):
    dest = tmp_path / "proj"
    outside = tmp_path / "evil.java"
    stats = extract_zip(
        dest, _zip({"p/A.java": b"ok", "p/../../../evil.java": b"pwned"})
    )
    assert stats.files == 1
    assert not outside.exists()


def test_extract_zip_skips_symlinks(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("p/A.java", b"ok")
        info = zipfile.ZipInfo("p/link.java")
        info.external_attr = (0o120777 << 16)  # symlink
        zf.writestr(info, b"/etc/passwd")
    buf.seek(0)

    dest = tmp_path / "proj"
    stats = extract_zip(dest, buf)
    assert stats.files == 1
    assert not (dest / "link.java").exists()
    assert "심볼릭 링크 제외" in stats.reasons


def test_extract_zip_rejects_bad_archive(tmp_path):
    with pytest.raises(UploadError):
        extract_zip(tmp_path / "proj", io.BytesIO(b"not a zip"))


def test_extract_zip_rejects_empty_result(tmp_path):
    with pytest.raises(UploadError):
        extract_zip(tmp_path / "proj", _zip({"p/a.jar": b"x"}))


# --------------------------------------------------------------------------- #
# 목적지 이름
# --------------------------------------------------------------------------- #
def test_unique_dir_avoids_collision(tmp_path):
    first = unique_dir(tmp_path, "my proj")
    first.mkdir()
    second = unique_dir(tmp_path, "my proj")
    assert first.name == "my-proj"
    assert second.name == "my-proj-2"


def test_unique_dir_sanitizes(tmp_path):
    assert unique_dir(tmp_path, "../../etc").parent == tmp_path
    assert unique_dir(tmp_path, "").name == "upload"


# --------------------------------------------------------------------------- #
# 엔드포인트 (multipart 처리까지 실제로 태운다)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path):
    """tmp 설정으로 앱을 다시 읽어 실제 레지스트리·업로드 폴더를 건드리지 않는다.

    app.py 는 import 시점에 config 를 읽으므로 reload 가 필요하다. 끝나고
    원래 환경으로 되돌린 뒤 한 번 더 reload 해서 다른 테스트에 새지 않게 한다.
    """
    conf = {
        "project": {"name": "T", "source_roots": [str(tmp_path / "src")], "layers": []},
        "parse": {"include": ["**/*.java", "**/*.xml", "**/*.py"], "exclude": []},
        "llm": {"provider": "template"},
        "output": {
            "docs_dir": str(tmp_path / "docs"),
            "index_file": str(tmp_path / "docs/index.json"),
            "workspace_dir": str(tmp_path / "projects"),
        },
        "server": {
            "upload_dir": str(tmp_path / "uploads"),
            "browse_roots": [str(tmp_path / "uploads")],
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(conf), encoding="utf-8")
    (tmp_path / "src").mkdir()

    previous = os.environ.get("LLMWIKI_CONFIG")
    os.environ["LLMWIKI_CONFIG"] = str(path)
    import llmwiki.server.app as appmod

    importlib.reload(appmod)
    try:
        yield TestClient(appmod.app), tmp_path
    finally:
        if previous is None:
            os.environ.pop("LLMWIKI_CONFIG", None)
        else:
            os.environ["LLMWIKI_CONFIG"] = previous
        importlib.reload(appmod)


def _wait(c: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았습니다")


def test_upload_folder_registers_and_parses(client):
    c, root = client
    files = [
        ("files", ("A.java", b"package p; public class A {}", "text/plain")),
        ("files", ("m.xml", b"<mapper/>", "text/xml")),
    ]
    data = {"paths": ["loan/src/A.java", "loan/src/m.xml"], "name": "loan"}
    res = c.post("/api/projects/upload", files=files, data=data)
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["upload"]["files"] == 2
    dest = Path(body["project"]["roots"][0])
    assert dest.is_relative_to(root / "uploads")
    # 공통 최상위(loan/)는 벗겨지고 src/ 부터 남는다
    assert (dest / "src" / "A.java").exists()

    assert _wait(c, body["job"])["state"] == "done"
    assert body["project"]["id"] in [p["id"] for p in c.get("/api/projects").json()["projects"]]


def test_upload_zip_registers(client):
    c, root = client
    buf = _zip({"proj/src/A.java": b"package p; public class A {}"})
    res = c.post(
        "/api/projects/upload",
        files=[("files", ("proj.zip", buf.getvalue(), "application/zip"))],
        data={"name": ""},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["upload"]["files"] == 1
    assert (Path(body["project"]["roots"][0]) / "src" / "A.java").exists()
    assert _wait(c, body["job"])["state"] == "done"


def test_upload_rejects_when_all_filtered(client):
    c, _ = client
    res = c.post(
        "/api/projects/upload",
        files=[("files", ("a.jar", b"\x00", "application/java-archive"))],
        data={"paths": ["p/a.jar"]},
    )
    assert res.status_code == 400
    assert "소스 파일이 없습니다" in res.json()["detail"]


def test_upload_traversal_stays_inside(client):
    c, root = client
    res = c.post(
        "/api/projects/upload",
        files=[
            ("files", ("A.java", b"ok", "text/plain")),
            ("files", ("evil.java", b"pwned", "text/plain")),
        ],
        data={"paths": ["p/A.java", "p/../../../evil.java"], "name": "p"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["upload"]["files"] == 1
    assert not (root / "evil.java").exists()
    assert not (root.parent / "evil.java").exists()


# --------------------------------------------------------------------------- #
# 나눠 보내는 업로드 (세션)
# --------------------------------------------------------------------------- #
def test_chunked_upload_assembles_and_parses(client):
    c, root = client
    sid = c.post("/api/uploads", json={"name": "chunked"}).json()["upload_id"]

    # 두 묶음으로 나눠 보낸다 (클라이언트가 공통 최상위를 이미 벗긴 상태)
    r1 = c.post(
        f"/api/uploads/{sid}/files",
        files=[("files", ("A.java", b"package p; public class A {}", "text/plain"))],
        data={"paths": ["src/A.java"]},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["upload"]["files"] == 1

    r2 = c.post(
        f"/api/uploads/{sid}/files",
        files=[("files", ("m.xml", b"<mapper/>", "text/xml"))],
        data={"paths": ["src/m.xml"]},
    )
    # 통계는 누적이어야 한다
    assert r2.json()["upload"]["files"] == 2

    body = c.post(f"/api/uploads/{sid}/finish").json()
    dest = Path(body["project"]["roots"][0])
    assert dest.is_relative_to(root / "uploads")
    assert (dest / "src" / "A.java").exists()
    assert (dest / "src" / "m.xml").exists()
    assert _wait(c, body["job"])["state"] == "done"


def test_chunk_retry_overwrites_same_file(client):
    """끊긴 묶음을 다시 보내도 중복이 아니라 덮어쓰기여야 한다."""
    c, _ = client
    sid = c.post("/api/uploads", json={"name": "retry"}).json()["upload_id"]
    for _ in range(2):
        c.post(
            f"/api/uploads/{sid}/files",
            files=[("files", ("A.java", b"package p; public class A {}", "text/plain"))],
            data={"paths": ["src/A.java"]},
        )
    body = c.post(f"/api/uploads/{sid}/finish").json()
    dest = Path(body["project"]["roots"][0])
    assert [p.name for p in (dest / "src").iterdir()] == ["A.java"]


def test_chunked_upload_keeps_paths_verbatim(client):
    """배치는 서버가 최상위를 벗기면 안 된다 — 묶음마다 최상위가 달라 보인다."""
    c, _ = client
    sid = c.post("/api/uploads", json={"name": "verbatim"}).json()["upload_id"]
    c.post(
        f"/api/uploads/{sid}/files",
        files=[("files", ("A.java", b"package p; public class A {}", "text/plain"))],
        data={"paths": ["only/A.java"]},
    )
    dest = Path(c.post(f"/api/uploads/{sid}/finish").json()["project"]["roots"][0])
    assert (dest / "only" / "A.java").exists()


def test_chunk_blocks_traversal(client):
    c, root = client
    sid = c.post("/api/uploads", json={"name": "sec"}).json()["upload_id"]
    r = c.post(
        f"/api/uploads/{sid}/files",
        files=[
            ("files", ("A.java", b"ok", "text/plain")),
            ("files", ("evil.java", b"pwned", "text/plain")),
        ],
        data={"paths": ["A.java", "../../../evil.java"]},
    )
    assert r.json()["upload"]["files"] == 1
    assert not (root / "evil.java").exists()
    c.delete(f"/api/uploads/{sid}")


def test_finish_rejects_empty_session_and_cleans_up(client):
    c, root = client
    sid = c.post("/api/uploads", json={"name": "empty"}).json()["upload_id"]
    c.post(
        f"/api/uploads/{sid}/files",
        files=[("files", ("a.jar", b"\x00", "application/java-archive"))],
        data={"paths": ["a.jar"]},
    )
    res = c.post(f"/api/uploads/{sid}/finish")
    assert res.status_code == 400
    assert "소스 파일이 없습니다" in res.json()["detail"]
    assert not (root / "uploads" / "empty").exists()


def test_abort_removes_partial_upload(client):
    c, root = client
    sid = c.post("/api/uploads", json={"name": "aborted"}).json()["upload_id"]
    c.post(
        f"/api/uploads/{sid}/files",
        files=[("files", ("A.java", b"package p; public class A {}", "text/plain"))],
        data={"paths": ["A.java"]},
    )
    assert (root / "uploads" / "aborted").exists()
    assert c.delete(f"/api/uploads/{sid}").json()["removed"] is True
    assert not (root / "uploads" / "aborted").exists()


def test_unknown_session_is_reported_clearly(client):
    c, _ = client
    res = c.post(
        "/api/uploads/nope/files",
        files=[("files", ("A.java", b"x", "text/plain"))],
        data={"paths": ["A.java"]},
    )
    assert res.status_code == 400
    assert "업로드 세션을 찾을 수 없습니다" in res.json()["detail"]


def test_concurrent_sessions_do_not_collide(client):
    c, _ = client
    a = c.post("/api/uploads", json={"name": "same"}).json()["upload_id"]
    b = c.post("/api/uploads", json={"name": "same"}).json()["upload_id"]
    assert a != b
    for sid, body in ((a, b"class A {}"), (b, b"class B {}")):
        c.post(
            f"/api/uploads/{sid}/files",
            files=[("files", ("X.java", body, "text/plain"))],
            data={"paths": ["X.java"]},
        )
    da = Path(c.post(f"/api/uploads/{a}/finish").json()["project"]["roots"][0])
    db = Path(c.post(f"/api/uploads/{b}/finish").json()["project"]["roots"][0])
    assert da != db
    assert (da / "X.java").read_bytes() == b"class A {}"
    assert (db / "X.java").read_bytes() == b"class B {}"


def test_providers_lists_configured_ones(client):
    c, _ = client
    body = c.get("/api/providers").json()
    ids = [p["id"] for p in body["providers"]]
    # config 의 llm 아래 dict 키만 (provider: 문자열은 빠진다)
    assert body["default"] == "template"
    assert "template" in ids


def test_generate_rejects_unknown_provider(client):
    c, _ = client
    res = c.post("/api/generate", json={"provider": "no-such-llm"})
    assert res.status_code == 400
    assert "설정에 없는 공급자" in res.json()["detail"]


def test_generate_honours_picked_provider(client):
    c, root = client
    (root / "src" / "A.java").write_text(
        "package p;\n"
        "import org.springframework.stereotype.Controller;\n"
        "import org.springframework.web.bind.annotation.RequestMapping;\n"
        "@Controller @RequestMapping(\"/a\")\n"
        "public class AController { @RequestMapping(\"/l.do\") public String l(){return \"v\";} }\n",
        encoding="utf-8",
    )
    assert _wait(c, c.post("/api/projects/default/parse").json()["job"])["state"] == "done"

    job_id = c.post(
        "/api/generate", json={"provider": "template", "project": "default"}
    ).json()["job"]
    assert _wait(c, job_id, timeout=40)["state"] == "done"
    # 작업 기록에 고른 공급자가 남아야 나중에 무엇으로 만든 문서인지 알 수 있다
    assert c.get(f"/api/jobs/{job_id}").json()["provider"] == "template"


def test_with_provider_does_not_mutate_base_config(client):
    """한 요청의 선택이 서버 기본 공급자를 바꾸면 안 된다."""
    import llmwiki.server.app as appmod

    before = appmod.cfg.provider
    c, _ = client
    c.post("/api/generate", json={"provider": "template"})
    assert appmod.cfg.provider == before
    assert c.get("/api/meta").json()["provider"] == before


def test_removing_uploaded_project_cleans_the_copy(client):
    c, root = client
    res = c.post(
        "/api/projects/upload",
        files=[("files", ("A.java", b"package p; public class A {}", "text/plain"))],
        data={"paths": ["gone/A.java"], "name": "gone"},
    )
    body = res.json()
    _wait(c, body["job"])
    dest = Path(body["project"]["roots"][0])
    assert dest.exists()

    assert c.delete(f"/api/projects/{body['project']['id']}").json()["removed"] is True
    # 업로드 사본은 우리가 만든 것이므로 함께 치운다 (원본은 사용자 PC 에 있다)
    assert not dest.exists()
    assert (root / "uploads").exists()
