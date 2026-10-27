"""EngPaperTeacher - local web app: read any paper, click words, learn."""
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import chunking
from . import course
from . import llm
from . import pdf_parse
from . import tts
from .dict_lookup import ECDICT
from .translate import Translator

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = DATA / "docs"
DOCS.mkdir(parents=True, exist_ok=True)
(ROOT / "static").mkdir(exist_ok=True)

_cfg = {}
_cfg_path = ROOT / "config.json"
if _cfg_path.exists():
    try:
        _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
    except Exception:
        _cfg = {}

app = FastAPI(title="EngPaperTeacher")
translator = Translator(proxy=_cfg.get("proxy"),
                        contact=_cfg.get("translate_contact") or "")

_dict_lock = threading.Lock()
_dict = None

_DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _cfg_int(key: str, default: int, low: int = 1, high: int = 10_000) -> int:
    try:
        value = int(_cfg.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def get_dict():
    global _dict
    with _dict_lock:
        if _dict is None:
            db = DATA / "stardict.db"
            if db.exists():
                try:
                    _dict = ECDICT(db)
                except Exception:
                    _dict = None
        return _dict


def _log_llm_error(where: str, detail: str):
    try:
        line = "[%s] %s: %s\n" % (_dt.datetime.now().isoformat(timespec="seconds"),
                                  where, detail)
        with (DATA / "llm_errors.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


_AUTO_MAX = 262144  # uniform truncation-safety cap (DeepSeek allows up to 384k)


def _llm_opts(cfg: dict):
    """Thinking effort + max output tokens from the frontend config."""
    effort = str(cfg.get("effort") or "off").lower()
    if effort not in ("off", "low", "high", "max"):
        effort = "off"
    try:
        mt = int(cfg.get("max_tokens") or 0)
    except (TypeError, ValueError):
        mt = 0
    if mt <= 0:
        mt = _AUTO_MAX
    return effort, mt


def _slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.").lower()
    return (s or "doc")[:60]


def _doc_dir(doc_id: str) -> Path:
    if not _DOC_ID_RE.fullmatch(doc_id or ""):
        raise HTTPException(400, "invalid doc_id")
    base = DOCS.resolve()
    d = (DOCS / doc_id).resolve()
    if d.parent != base:
        raise HTTPException(400, "invalid doc_id")
    if not (d / "doc.json").exists():
        raise HTTPException(404, "doc not found")
    return d


def _doc_meta(ddir: Path) -> dict:
    try:
        data = json.loads((ddir / "doc.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@app.get("/api/health")
def health():
    d = get_dict()
    return {"ok": True, "dict_installed": d is not None}


@app.get("/api/docs")
def list_docs():
    out = []
    for d in sorted(DOCS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        meta = d / "doc.json"
        if meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                out.append({"doc_id": d.name,
                            "title": m.get("title") or d.name,
                            "page_count": m.get("page_count"),
                            "mtime": d.stat().st_mtime})
            except Exception:
                pass
    return {"docs": out}


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF supported for now")
    max_bytes = _cfg_int("max_upload_mb", 80) * 1024 * 1024
    fd, tmp_name = tempfile.mkstemp(prefix="ept-upload-", suffix=".pdf", dir=str(DATA))
    tmp_path = Path(tmp_name)
    try:
        size = 0
        digest = hashlib.sha256()
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        413, "PDF too large (limit %d MB)" % (max_bytes // (1024 * 1024)))
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "empty file")
        sha = digest.hexdigest()
        slug = _slugify(Path(filename).stem)
        doc_id = slug
        ddir = DOCS / doc_id
        if ddir.exists():
            prev = _doc_meta(ddir)
            if prev.get("source_name") == filename and prev.get("source_sha256") == sha:
                src = ddir / "source.pdf"
                if not src.exists():
                    shutil.copyfile(tmp_path, src)
                return {"ok": True, "doc_id": doc_id, "title": prev.get("title") or doc_id,
                        "page_count": prev.get("page_count"),
                        "blocks": len(prev.get("blocks") or []), "duplicate": True}
            n = 1
            while (DOCS / f"{slug}-{n}").exists():
                n += 1
            doc_id = f"{slug}-{n}"
            ddir = DOCS / doc_id
        ddir.mkdir(parents=True, exist_ok=False)
        pdf_path = ddir / "source.pdf"
        shutil.copyfile(tmp_path, pdf_path)
        try:
            parsed = pdf_parse.parse_pdf(pdf_path)
        except Exception as e:
            shutil.rmtree(ddir, ignore_errors=True)
            raise HTTPException(500, f"parse failed: {e}")
        if not parsed.get("title") or parsed["title"] == pdf_path.stem:
            parsed["title"] = Path(filename).stem
        parsed["doc_id"] = doc_id
        parsed["source_name"] = filename
        parsed["source_sha256"] = sha
        parsed["source_size"] = size
        parsed["uploaded_at"] = _dt.datetime.now().isoformat(timespec="seconds")
        (ddir / "doc.json").write_text(
            json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "doc_id": doc_id, "title": parsed["title"],
                "page_count": parsed["page_count"], "blocks": len(parsed["blocks"]),
                "duplicate": False}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/api/doc/{doc_id}")
def get_doc(doc_id: str):
    d = _doc_dir(doc_id)
    return json.loads((d / "doc.json").read_text(encoding="utf-8"))


@app.delete("/api/doc/{doc_id}")
def delete_doc(doc_id: str):
    d = _doc_dir(doc_id)
    if _doc_job_running(doc_id):
        raise HTTPException(409, "batch generation is running; cancel it first")
    shutil.rmtree(d)
    return {"ok": True, "deleted": doc_id}


@app.patch("/api/doc/{doc_id}")
def rename_doc(doc_id: str, payload: dict = Body(...)):
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    d = _doc_dir(doc_id)
    meta = _doc_meta(d)
    meta["title"] = title[:200]
    (d / "doc.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "doc_id": doc_id, "title": meta["title"]}


@app.post("/api/doc/{doc_id}/reparse")
def reparse_doc(doc_id: str):
    d = _doc_dir(doc_id)
    if _doc_job_running(doc_id):
        raise HTTPException(409, "batch generation is running; cancel it first")
    src = d / "source.pdf"
    if not src.exists():
        raise HTTPException(400, "source PDF missing")
    meta = _doc_meta(d)
    try:
        parsed = pdf_parse.parse_pdf(src)
    except Exception as e:
        raise HTTPException(500, f"parse failed: {e}")
    if not parsed.get("title") or parsed["title"] == src.stem:
        parsed["title"] = meta.get("source_name") or doc_id
    parsed["doc_id"] = doc_id
    for key in ("source_name", "source_sha256", "source_size", "uploaded_at"):
        if key in meta:
            parsed[key] = meta[key]
    (d / "doc.json").write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "doc_id": doc_id, "title": parsed["title"],
            "page_count": parsed["page_count"], "blocks": len(parsed["blocks"]),
            "derived_stale": True}


@app.get("/api/word")
def word(q: str = Query(..., min_length=1, max_length=200)):
    d = get_dict()
    entry = d.lookup(q) if d else None
    if entry:
        return {"ok": True, "source": "ecdict", "entry": entry,
                "word": q.strip()}
    res = translator.translate(q)
    if res.get("ok"):
        return {"ok": True, "source": res["source"], "entry": None,
                "word": q.strip(), "translation": res["text"]}
    return {"ok": False, "source": None, "entry": None, "word": q.strip(),
            "errors": res.get("errors") or []}


@app.get("/api/translate")
def translate(text: str = Query(..., min_length=1, max_length=8000)):
    return translator.translate(text)


@app.post("/api/translate")
def translate_with_llm(payload: dict = Body(...)):
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    if len(text) > 8000:
        raise HTTPException(400, "text too long")
    res = translator.translate(text)
    if res.get("ok"):
        return res
    cfg = payload.get("llm") or {}
    base_url = (cfg.get("base_url") or "").strip()
    api_key = cfg.get("api_key") or ""
    model = (cfg.get("model") or "").strip()
    if not (base_url and model):
        return res
    effort, mt = _llm_opts(cfg)
    prompt = ("Translate the following English passage into Simplified Chinese. "
              "Output only the translation, with no explanation or quotes:\n\n" + text)
    try:
        out = llm.chat(base_url, api_key, model,
                       [{"role": "user", "content": prompt}],
                       proxy=_cfg.get("proxy"), max_tokens=min(mt, 4096),
                       temperature=0.2, timeout=90, effort=effort)
        if out.strip():
            return {"ok": True, "source": "llm", "text": out.strip()}
    except llm.LLMError as e:
        _log_llm_error("translate", str(e))
        res.setdefault("errors", []).append("llm: " + str(e))
    return res


_chunk_cache = OrderedDict()
_CHUNK_CACHE_MAX = 2000

_jobs = {}
_jobs_lock = threading.Lock()
_JOBS_MAX = 50


def _doc_job_running(doc_id: str) -> bool:
    with _jobs_lock:
        return any(j.get("doc_id") == doc_id and j.get("state") == "running"
                   for j in _jobs.values())


@app.get("/api/chunk")
def chunk(text: str = Query(..., min_length=1, max_length=8000)):
    key = text.strip()
    if key in _chunk_cache:
        _chunk_cache.move_to_end(key)
        return {"ok": True, "chunks": _chunk_cache[key], "cached": True}
    try:
        chunks = chunking.chunk_text(key)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"chunk failed: {e}")
    _chunk_cache[key] = chunks
    while len(_chunk_cache) > _CHUNK_CACHE_MAX:
        _chunk_cache.popitem(last=False)
    return {"ok": True, "chunks": chunks, "cached": False}


@app.post("/api/doc/{doc_id}/chunk_all")
def chunk_all(doc_id: str):
    d = _doc_dir(doc_id)
    doc = json.loads((d / "doc.json").read_text(encoding="utf-8"))
    result = {}
    total = 0
    n = 0
    for b in doc.get("blocks", []):
        if b.get("kind") != "para":
            continue
        for s in b.get("sentences", []):
            key = s.strip()
            if not key:
                continue
            cs = chunking.chunk_text(key)
            result[key] = cs
            total += len(cs)
            n += 1
    (d / "chunks.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "sentences": n, "chunks": total}


@app.get("/api/doc/{doc_id}/chunks")
def get_chunks(doc_id: str):
    path = _doc_dir(doc_id) / "chunks.json"
    if not path.exists():
        raise HTTPException(404, "chunks not generated yet")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/chunk/refine")
def chunk_refine(payload: dict = Body(...)):
    text = (payload.get("text") or "").strip()
    cfg = payload.get("llm") or {}
    base_url = (cfg.get("base_url") or "").strip()
    api_key = cfg.get("api_key") or ""
    model = (cfg.get("model") or "").strip()
    if not (text and base_url and model):
        raise HTTPException(400, "text / llm.base_url / llm.model required")
    effort, mt = _llm_opts(cfg)
    try:
        out = llm.refine_sentence(base_url, api_key, model, text,
                                  proxy=_cfg.get("proxy"),
                                  effort=effort, max_tokens=mt)
    except llm.LLMError as e:
        _log_llm_error("refine", str(e))
        raise HTTPException(502, str(e))
    return {"ok": True, **out}


@app.post("/api/llm/models")
def llm_models(payload: dict = Body(...)):
    cfg = payload.get("llm") or {}
    base_url = (cfg.get("base_url") or "").strip()
    api_key = cfg.get("api_key") or ""
    if not base_url:
        raise HTTPException(400, "llm.base_url required")
    try:
        ids = llm.list_models(base_url, api_key, proxy=_cfg.get("proxy"))
    except llm.LLMError as e:
        _log_llm_error("models", str(e))
        raise HTTPException(502, str(e))
    return {"ok": True, "models": ids}


@app.post("/api/llm/test")
def llm_test(payload: dict = Body(...)):
    cfg = payload.get("llm") or {}
    base_url = (cfg.get("base_url") or "").strip()
    api_key = cfg.get("api_key") or ""
    model = (cfg.get("model") or "").strip()
    if not (base_url and model):
        raise HTTPException(400, "llm.base_url / llm.model required")
    effort, mt = _llm_opts(cfg)
    try:
        out = llm.chat(base_url, api_key, model,
                       [{"role": "user", "content": "Reply with exactly: OK"}],
                       proxy=_cfg.get("proxy"), max_tokens=mt,
                       temperature=0.0, timeout=60, effort=effort)
    except llm.LLMError as e:
        _log_llm_error("test", str(e))
        raise HTTPException(502, str(e))
    return {"ok": True, "reply": out.strip()[:80]}


_tts = tts.TTS(DATA / "tts_cache", proxy=_cfg.get("proxy"),
               max_files=_cfg_int("tts_cache_max_files", 2000, low=1))
_tts_voices_cache: dict = {"data": None}


@app.get("/api/tts/voices")
def tts_voices():
    if _tts_voices_cache["data"] is None:
        try:
            _tts_voices_cache["data"] = tts.list_voices()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, "voice list failed: " + str(e))
    return {"ok": True, "voices": _tts_voices_cache["data"]}


@app.get("/api/tts")
def tts_get(text: str = Query(..., min_length=1),
            voice: str = "en-US-AriaNeural", rate: str = "+0%"):
    try:
        path, boundaries, cached = _tts.synthesize(text, voice=voice, rate=rate)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, "tts failed: " + str(e))
    return FileResponse(str(path), media_type="audio/mpeg",
                        headers={"Cache-Control": "public, max-age=86400",
                                 "X-TTS-Boundaries": str(len(boundaries)),
                                 "X-TTS-Cached": "1" if cached else "0"})


@app.get("/api/tts/meta")
def tts_meta(text: str = Query(..., min_length=1),
             voice: str = "en-US-AriaNeural", rate: str = "+0%"):
    try:
        path, boundaries, cached = _tts.synthesize(text, voice=voice, rate=rate)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, "tts failed: " + str(e))
    return {"ok": True, "boundaries": boundaries, "cached": cached}


@app.post("/api/doc/{doc_id}/course/units")
def course_units_build(doc_id: str):
    d = _doc_dir(doc_id)
    doc = json.loads((d / "doc.json").read_text(encoding="utf-8"))
    units = course.build_units(doc)
    (d / "units.json").write_text(json.dumps(units, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    return {"ok": True, "units": units}


@app.get("/api/doc/{doc_id}/course/units")
def course_units_get(doc_id: str):
    d = _doc_dir(doc_id)
    path = d / "units.json"
    if not path.exists():
        raise HTTPException(404, "units not built")
    units = json.loads(path.read_text(encoding="utf-8"))
    lessons = d / "lessons"
    have = set()
    if lessons.exists():
        for p in lessons.glob("unit*.json"):
            try:
                have.add(int(p.stem[4:]))
            except ValueError:
                pass
    for u in units:
        u["has_lesson"] = u.get("id") in have
    return {"ok": True, "units": units}


def _llm_from_payload(payload: dict):
    cfg = payload.get("llm") or {}
    base_url = (cfg.get("base_url") or "").strip()
    api_key = cfg.get("api_key") or ""
    model = (cfg.get("model") or "").strip()
    if not (base_url and model):
        raise HTTPException(400, "llm.base_url / llm.model required")
    return cfg, base_url, api_key, model


def _enrich_lesson_vocab(lesson: dict):
    dic = get_dict()
    if not dic:
        return
    for v in lesson.get("vocab", []):
        if not isinstance(v, dict):
            continue
        w = str(v.get("word", ""))
        entry = dic.lookup(w) if w else None
        if entry:
            if not v.get("phonetic"):
                v["phonetic"] = entry.get("phonetic") or ""
            if not v.get("pos"):
                v["pos"] = entry.get("pos") or ""
            if not v.get("meaning_cn"):
                v["meaning_cn"] = (entry.get("translation") or [""])[0]
            v["tags"] = entry.get("tags") or []


def _build_lesson(doc: dict, unit: dict, cfg: dict, ddir: Path, doc_id: str):
    base_url = (cfg.get("base_url") or "").strip()
    api_key = cfg.get("api_key") or ""
    model = (cfg.get("model") or "").strip()
    effort, mt = _llm_opts(cfg)
    lesson = course.generate_lesson(doc, unit, base_url, api_key, model,
                                    proxy=_cfg.get("proxy"),
                                    effort=effort, max_tokens=mt)
    _enrich_lesson_vocab(lesson)
    lessons = ddir / "lessons"
    lessons.mkdir(exist_ok=True)
    (lessons / f"unit{unit['id']:03d}.json").write_text(
        json.dumps(lesson, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = course.lesson_rows(lesson, f"{doc_id}/unit{unit['id']:03d}")
    added = course.add_bank_rows(DATA / "vocab_bank.tsv", rows) if rows else 0
    return lesson, added


@app.post("/api/doc/{doc_id}/course/lesson/{unit_id}")
def course_lesson_generate(doc_id: str, unit_id: int, payload: dict = Body(...)):
    d = _doc_dir(doc_id)
    units_path = d / "units.json"
    if not units_path.exists():
        raise HTTPException(400, "build units first")
    units = json.loads(units_path.read_text(encoding="utf-8"))
    unit = next((u for u in units if u["id"] == unit_id), None)
    if unit is None:
        raise HTTPException(404, "unit not found")
    cfg, _, _, _ = _llm_from_payload(payload)
    doc = json.loads((d / "doc.json").read_text(encoding="utf-8"))
    try:
        lesson, added = _build_lesson(doc, unit, cfg, d, doc_id)
    except llm.LLMError as e:
        _log_llm_error("lesson", str(e))
        raise HTTPException(502, str(e))
    return {"ok": True, "lesson": lesson, "vocab_added": added}


@app.get("/api/doc/{doc_id}/course/lesson/{unit_id}")
def course_lesson_get(doc_id: str, unit_id: int):
    d = _doc_dir(doc_id)
    path = d / "lessons" / f"unit{unit_id:03d}.json"
    if not path.exists():
        raise HTTPException(404, "lesson not generated")
    return {"ok": True, "lesson": json.loads(path.read_text(encoding="utf-8"))}


def _job_public(job: dict) -> dict:
    return {k: job.get(k) for k in (
        "id", "doc_id", "state", "total", "done", "current", "errors",
        "vocab_added", "started_at", "finished_at")}


def _prune_jobs_locked():
    now = _dt.datetime.now()
    for key in list(_jobs):
        job = _jobs[key]
        finished = job.get("_finished")
        if job.get("state") != "running" and finished:
            if (now - finished).total_seconds() > 3600:
                _jobs.pop(key, None)
    while len(_jobs) > _JOBS_MAX:
        oldest = min(
            (j for j in _jobs.values() if j.get("state") != "running"),
            key=lambda j: j.get("_started") or now,
            default=None)
        if not oldest:
            break
        _jobs.pop(oldest["id"], None)


def _run_batch(job_id: str, ddir: Path, doc_id: str, doc: dict,
               targets: list, cfg: dict):
    for unit in targets:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            if job.get("cancel"):
                job["state"] = "cancelled"
                job["finished_at"] = _dt.datetime.now().isoformat(timespec="seconds")
                job["_finished"] = _dt.datetime.now()
                return
            job["current"] = unit.get("title") or ""
        try:
            _, added = _build_lesson(doc, unit, cfg, ddir, doc_id)
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["done"] += 1
                job["vocab_added"] += added
        except Exception as e:  # noqa: BLE001
            _log_llm_error("batch", "unit %s: %s" % (unit.get("id"), e))
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["done"] += 1
                job["errors"].append({
                    "unit": unit.get("id"),
                    "title": unit.get("title"),
                    "error": str(e)[:300]})
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job.get("state") == "cancelled":
            return
        job["current"] = ""
        if job.get("cancel"):
            job["state"] = "cancelled"
        else:
            job["state"] = "done_with_errors" if job["errors"] else "done"
        job["finished_at"] = _dt.datetime.now().isoformat(timespec="seconds")
        job["_finished"] = _dt.datetime.now()


@app.post("/api/doc/{doc_id}/course/batch")
def course_batch_start(doc_id: str, payload: dict = Body(...)):
    d = _doc_dir(doc_id)
    units_path = d / "units.json"
    if not units_path.exists():
        raise HTTPException(400, "build units first")
    cfg, _, _, _ = _llm_from_payload(payload)
    units = json.loads(units_path.read_text(encoding="utf-8"))
    only_missing = bool(payload.get("only_missing", True))
    lessons = d / "lessons"
    have = set()
    if lessons.exists():
        for p in lessons.glob("unit*.json"):
            try:
                have.add(int(p.stem[4:]))
            except ValueError:
                pass
    targets = [u for u in units if not only_missing or u.get("id") not in have]
    if not targets:
        return {"ok": True, "job": None, "units": 0}
    doc = json.loads((d / "doc.json").read_text(encoding="utf-8"))
    job_id = uuid.uuid4().hex[:12]
    now = _dt.datetime.now()
    job = {"id": job_id, "doc_id": doc_id, "state": "running", "total": len(targets),
           "done": 0, "current": "", "errors": [], "vocab_added": 0,
           "started_at": now.isoformat(timespec="seconds"), "finished_at": None,
           "cancel": False, "_started": now, "_finished": None}
    with _jobs_lock:
        for existing in _jobs.values():
            if existing.get("doc_id") == doc_id and existing.get("state") == "running":
                return {"ok": True, "job": _job_public(existing), "units": existing["total"]}
        _prune_jobs_locked()
        _jobs[job_id] = job
    threading.Thread(target=_run_batch,
                     args=(job_id, d, doc_id, doc, targets, cfg),
                     daemon=True).start()
    return {"ok": True, "job": _job_public(job), "units": len(targets)}


@app.get("/api/doc/{doc_id}/course/batch/{job_id}")
def course_batch_status(doc_id: str, job_id: str):
    _doc_dir(doc_id)
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job.get("doc_id") != doc_id:
        raise HTTPException(404, "job not found")
    return {"ok": True, "job": _job_public(job)}


@app.post("/api/doc/{doc_id}/course/batch/{job_id}/cancel")
def course_batch_cancel(doc_id: str, job_id: str):
    _doc_dir(doc_id)
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.get("doc_id") != doc_id:
            raise HTTPException(404, "job not found")
        job["cancel"] = True
    return {"ok": True}


@app.get("/api/vocab")
def vocab_list(q: str = ""):
    rows = course.read_bank(DATA / "vocab_bank.tsv")
    ql = (q or "").strip().lower()
    if ql:
        rows = [r for r in rows if ql in (
            r.get("word", "") + " " + r.get("meaning_cn", "") + " " +
            r.get("collocations", "") + " " + r.get("note", "")).lower()]
    return {"ok": True, "rows": rows}


@app.post("/api/vocab/add")
def vocab_add(payload: dict = Body(...)):
    word = str(payload.get("word") or "").strip()
    if not word:
        raise HTTPException(400, "word required")
    row = {"date": _dt.date.today().isoformat(), "word": word,
           "phonetic": payload.get("phonetic", ""), "pos": payload.get("pos", ""),
           "meaning_cn": payload.get("meaning_cn", ""),
           "collocations": payload.get("collocations", ""), "word_family": "",
           "example": payload.get("example", ""),
           "source": payload.get("source", "manual"), "note": payload.get("note", "")}
    dic = get_dict()
    entry = dic.lookup(word) if dic else None
    if entry:
        row["phonetic"] = row["phonetic"] or entry.get("phonetic") or ""
        row["pos"] = row["pos"] or entry.get("pos") or ""
        row["meaning_cn"] = row["meaning_cn"] or (entry.get("translation") or [""])[0]
    added = course.add_bank_rows(DATA / "vocab_bank.tsv", [row])
    return {"ok": True, "added": added, "row": row}


@app.post("/api/vocab/delete")
def vocab_delete(payload: dict = Body(...)):
    words = payload.get("words")
    if not words:
        words = [payload.get("word")]
    if not isinstance(words, list):
        words = [words]
    removed = course.remove_bank_rows(DATA / "vocab_bank.tsv", words)
    return {"ok": True, "removed": removed}


@app.post("/api/vocab/update")
def vocab_update(payload: dict = Body(...)):
    word = str(payload.get("word") or "").strip()
    if not word:
        raise HTTPException(400, "word required")
    row = course.update_bank_row(DATA / "vocab_bank.tsv", word, payload.get("patch") or {})
    if row is None:
        raise HTTPException(404, "word not found")
    return {"ok": True, "row": row}


@app.get("/api/vocab/export")
def vocab_export():
    path = DATA / "vocab_bank.tsv"
    if not path.exists():
        raise HTTPException(404, "bank empty")
    return Response(content=path.read_text(encoding="utf-8-sig"),
                    media_type="text/tab-separated-values",
                    headers={"Content-Disposition": "attachment; filename=vocab_bank.tsv"})


app.mount("/", StaticFiles(directory=str(ROOT / "static"), html=True), name="static")
