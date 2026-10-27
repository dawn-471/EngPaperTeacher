def _upload(client, pdf_bytes, name="paper.pdf"):
    return client.post(
        "/api/upload",
        files={"file": (name, pdf_bytes, "application/pdf")},
    )


def test_health_and_static(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "docs_dir" not in r.json()
    r = client.get("/")
    assert r.status_code == 200
    assert "EngPaperTeacher" in r.text


def test_upload_list_get_delete(client, sample_pdf):
    r = _upload(client, sample_pdf)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["doc_id"] == "paper"
    assert body["duplicate"] is False
    assert "Community Garden" in body["title"]

    r = client.get("/api/docs")
    assert [d["doc_id"] for d in r.json()["docs"]] == ["paper"]

    r = client.get("/api/doc/paper")
    assert r.status_code == 200
    assert "Community Garden" in r.json()["title"]
    assert r.json()["source_sha256"]

    r = client.delete("/api/doc/paper")
    assert r.status_code == 200
    assert client.get("/api/doc/paper").status_code == 404


def test_upload_duplicate_and_new_version(client, sample_pdf):
    first = _upload(client, sample_pdf).json()
    again = _upload(client, sample_pdf).json()
    assert again["duplicate"] is True
    assert again["doc_id"] == first["doc_id"]
    assert len(client.get("/api/docs").json()["docs"]) == 1

    changed = sample_pdf + b"\n% different bytes"
    other = _upload(client, changed).json()
    assert other["duplicate"] is False
    assert other["doc_id"] == "paper-1"
    assert len(client.get("/api/docs").json()["docs"]) == 2


def test_upload_rejects_non_pdf(client):
    r = client.post("/api/upload", files={"file": ("paper.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_doc_id_traversal_rejected(client):
    r = client.get("/api/doc/..%5Cdocs%5Cmain")
    assert r.status_code == 400
    r = client.get("/api/doc/%2e%2e")
    assert r.status_code in (400, 404)


def test_llm_models_is_post_only(client):
    assert client.get("/api/llm/models").status_code == 404
    r = client.post("/api/llm/models", json={"llm": {}})
    assert r.status_code == 400
    assert "base_url" in r.json()["detail"]


def test_vocab_crud(client):
    r = client.post("/api/vocab/add", json={"word": "compost", "meaning_cn": "堆肥"})
    assert r.status_code == 200
    assert r.json()["added"] == 1

    r = client.get("/api/vocab")
    rows = r.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["word"] == "compost"

    r = client.get("/api/vocab", params={"q": "堆肥"})
    assert len(r.json()["rows"]) == 1

    r = client.post("/api/vocab/update",
                    json={"word": "compost", "patch": {"note": "重点词"}})
    assert r.status_code == 200
    assert r.json()["row"]["note"] == "重点词"

    r = client.post("/api/vocab/delete", json={"word": "compost"})
    assert r.status_code == 200
    assert r.json()["removed"] == 1
    assert client.get("/api/vocab").json()["rows"] == []


def test_translate_llm_fallback(client, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main.translator, "translate", lambda text, tl="zh-CN": {
        "ok": False, "source": None, "text": None, "errors": ["network down"]})
    monkeypatch.setattr(main.llm, "chat", lambda *a, **k: "LLM 译文")
    r = client.post("/api/translate", json={
        "text": "hello",
        "llm": {"base_url": "http://127.0.0.1:9/v1", "model": "mock"},
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "source": "llm", "text": "LLM 译文"}


def test_rename_and_reparse(client, sample_pdf):
    _upload(client, sample_pdf)
    r = client.patch("/api/doc/paper", json={"title": "New Title"})
    assert r.status_code == 200
    assert client.get("/api/doc/paper").json()["title"] == "New Title"
    r = client.post("/api/doc/paper/reparse")
    assert r.status_code == 200
    assert "Community Garden" in r.json()["title"]


def test_batch_job_lifecycle(client, sample_pdf, monkeypatch):
    import time

    import app.main as main

    _upload(client, sample_pdf)
    r = client.post("/api/doc/paper/course/units")
    assert r.status_code == 200
    total = len(r.json()["units"])
    assert total

    seen = []

    def fake_build(doc, unit, cfg, ddir, doc_id):
        seen.append(unit["id"])
        return {}, 0

    monkeypatch.setattr(main, "_build_lesson", fake_build)
    r = client.post("/api/doc/paper/course/batch", json={
        "llm": {"base_url": "http://127.0.0.1:9/v1", "api_key": "x", "model": "mock"},
        "only_missing": True,
    })
    assert r.status_code == 200
    job = r.json()["job"]
    assert job and job["total"] == total

    status = job
    for _ in range(100):
        status = client.get("/api/doc/paper/course/batch/" + job["id"]).json()["job"]
        if status["state"] != "running":
            break
        time.sleep(0.02)
    assert status["state"] == "done"
    assert status["done"] == total
    assert sorted(seen) == sorted(u["id"] for u in client.get(
        "/api/doc/paper/course/units").json()["units"])
