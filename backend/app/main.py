from contextlib import asynccontextmanager
from pathlib import Path
import os, tempfile
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from . import config as C, db, queue, verses, storage, backup
from backend.engine.meter import suggest
from backend.executors.local import REGISTRY, get_executor

@asynccontextmanager
async def lifespan(app):
    db.init()
    try:
        storage.get().ensure_bucket()
    except Exception as e:                  # app still starts; audio endpoints answer 503 until storage is back
        print(f"[storage] unavailable: {e}")
    try:
        n = verses.load_seed(C.SEED_FILE)
        print(f"[seed] loaded {n} verses")
    except verses.VerseError as e:
        print(f"[seed] REJECTED: {e}")     # app still starts; fix verses.json and restart
    queue.start()
    backup.get().start()
    try: yield
    finally: backup.get().stop()

app = FastAPI(title="Sanskrit Śloka Studio", lifespan=lifespan)

class Source(BaseModel):
    work: str; reference: str; url: str | None = None; edition: str | None = None
class VerseIn(BaseModel):
    id: str; title: str | None = None; text: list[str] | str; source: Source
    notes: str | None = None; meter_hint: str | None = None
class WordMeaningIn(BaseModel):
    line: int; index: int; text: str; meaning: str; grammar: str | None = None
class SummaryIn(BaseModel):
    translation: str; explanation: str | None = None
class MeaningsIn(BaseModel):
    words: list[WordMeaningIn] = []; summary: SummaryIn | None = None
    origin: Literal["user", "machine", "seed"] = "user"; reviewed: bool | None = None
class SuggestIn(BaseModel):
    text: list[str] | str
class JobIn(BaseModel):
    verse_id: str; meter_id: str; voice_id: str = "steer"
    executor: str | None = None; device: str | None = None
    steps: int | None = Field(None, ge=1, le=64); seed: int = C.DEFAULT_SEED
class SettingsIn(BaseModel):
    executor: str | None = None; device: str | None = None; steps: int | None = Field(None, ge=1, le=64)
    colab_drive_dir: str | None = None; colab_timeout_s: int | None = Field(None, ge=10); colab_manual_timeout_s: int | None = Field(None, ge=60)

@app.get("/api/backup")
def backup_status(): return backup.get().status()
@app.post("/api/backup")
def backup_run():
    st = backup.get().backup_now()
    if st["last_error"]: raise HTTPException(500, st["last_error"])
    return st

@app.get("/api/meters")
def meters(): return db.q("SELECT id,name,syllable_count,sec_per_syll,is_prose FROM meters ORDER BY is_prose, syllable_count, name")
@app.get("/api/voices")
def voices(): return db.q("SELECT id,name,notice FROM voices WHERE enabled")

@app.get("/api/verses")
def list_verses():
    out = []
    for r in db.q("SELECT * FROM verses ORDER BY created_at, id"):
        v = verses.present(r)
        v["meanings"] = verses.get_meanings(r["id"])
        v["audio"] = db.q("SELECT j.id job_id,j.meter_id,j.voice_id,j.steps,a.duration FROM jobs j "
                          "JOIN assets a ON a.job_id=j.id WHERE j.verse_id=? AND j.status='done' ORDER BY j.id DESC", (r["id"],))
        out.append(v)
    return out

@app.post("/api/verses", status_code=201)
def add_verse(v: VerseIn):
    try: return {"id": verses.insert(v.model_dump(), "user")}
    except verses.VerseError as e: raise HTTPException(422 if "duplicate" not in str(e) else 409, str(e))

@app.get("/api/verses/{vid}")
def get_verse(vid: str):
    r = db.q1("SELECT * FROM verses WHERE id=?", (vid,))
    if not r: raise HTTPException(404, "no such verse")
    v = verses.present(r); v["meanings"] = verses.get_meanings(vid)
    return v

@app.put("/api/verses/{vid}/meanings")
def put_meanings(vid: str, b: MeaningsIn):
    reviewed = b.reviewed if b.reviewed is not None else b.origin != "machine"
    try:
        verses.set_meanings(vid, [w.model_dump() for w in b.words], b.summary.model_dump() if b.summary else None,
                            b.origin, reviewed)
    except KeyError: raise HTTPException(404, "no such verse")
    except verses.MeaningsError as e: raise HTTPException(422, str(e))
    return verses.get_meanings(vid)

@app.post("/api/meter-suggest")
def meter_suggest(b: SuggestIn):
    lines = b.text if isinstance(b.text, list) else b.text.splitlines()
    s = suggest(verses.padas(lines), [dict(m) for m in db.q("SELECT * FROM meters")])
    if not s: raise HTTPException(422, "no text")
    return s

@app.get("/api/settings")
def get_settings(): return db.get_settings()
@app.put("/api/settings")
def put_settings(s: SettingsIn):
    for k, v in s.model_dump(exclude_none=True).items():
        if k == "executor" and v not in REGISTRY: raise HTTPException(422, f"unknown executor '{v}'")
        if k == "device" and v not in ("cpu", "cuda"): raise HTTPException(422, "device must be cpu or cuda")
        db.set_setting(k, v)
    return db.get_settings()
_EXEC_INFO = {"local": ("This computer", "Runs the model here (CPU or CUDA).")}
@app.get("/api/executors")
def executors():
    out = []
    for n, cls in REGISTRY.items():
        lab, desc = _EXEC_INFO.get(n, (getattr(cls, "label", n), getattr(cls, "description", "")))
        out.append({"name": n, "label": lab, "description": desc})
    return out

@app.get("/api/executors/{name}/health")
def health(name: str):
    try: return get_executor(name).health()
    except ValueError as e: raise HTTPException(404, str(e))

@app.post("/api/jobs", status_code=201)
def create_job(j: JobIn):
    st = db.get_settings()
    try:
        jid = queue.submit(j.verse_id, j.meter_id, j.voice_id, j.executor or st["executor"], j.device or st["device"],
                           j.steps or int(st["steps"]), j.seed)
    except KeyError as e: raise HTTPException(404, f"unknown {e.args[0]}")
    except ValueError as e: raise HTTPException(422, str(e))
    return {"id": jid}

@app.get("/api/jobs")
def jobs(): return db.q("SELECT id,verse_id,meter_id,voice_id,executor,device,steps,status,progress,error,created_at FROM jobs ORDER BY id DESC LIMIT 100")
@app.get("/api/jobs/{jid}")
def job(jid: int):
    r = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    if not r: raise HTTPException(404, "no such job")
    r["asset"] = db.q1("SELECT duration, alignment_key IS NOT NULL AS aligned FROM assets WHERE job_id=?", (jid,))
    return r
@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: int):
    if not queue.cancel(jid): raise HTTPException(409, "job not cancellable")
    return {"ok": True}
def _object(key: str | None, request: Request, media: str, what: str):
    if not key: raise HTTPException(404, what)
    try:
        chunks, status, headers = storage.get().get_stream(key, request.headers.get("range"))
    except storage.NotFound: raise HTTPException(404, what)
    except storage.BadRange: raise HTTPException(416, "bad range")
    except Exception as e: raise HTTPException(503, f"storage unavailable: {e}")
    headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    return StreamingResponse(chunks, status_code=status, headers=headers, media_type=media)

@app.get("/api/jobs/{jid}/audio.mp3")
def audio(jid: int, request: Request):
    a = db.q1("SELECT mp3_key FROM assets WHERE job_id=?", (jid,))
    return _object(a and a["mp3_key"], request, "audio/mpeg", "no audio")

@app.get("/api/jobs/{jid}/alignment")
def alignment(jid: int, request: Request):
    a = db.q1("SELECT alignment_key FROM assets WHERE job_id=?", (jid,))
    return _object(a and a["alignment_key"], request, "application/json", "alignment unavailable")

MAX_RESULT_BYTES = 200 * 1024 * 1024

@app.get("/api/jobs/{jid}/bundle")
def bundle(jid: int):
    j = db.q1("SELECT executor FROM jobs WHERE id=?", (jid,))
    p = queue.job_dir(jid) / "bundle.zip"
    if not j or j["executor"] != "colab_manual" or not p.exists(): raise HTTPException(404, "no bundle")
    return FileResponse(p, media_type="application/zip", filename=f"job{jid}-bundle.zip")

@app.put("/api/jobs/{jid}/result")
async def upload_result(jid: int, request: Request):
    import zipfile
    from backend.executors.bundle import check_zip
    j = db.q1("SELECT executor,status FROM jobs WHERE id=?", (jid,))
    if not j: raise HTTPException(404, "no such job")
    if j["executor"] != "colab_manual" or j["status"] != "running":
        raise HTTPException(409, "job is not a running colab_manual job")
    wd = queue.job_dir(jid); wd.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=wd, suffix=".part")
    try:
        size = 0
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_RESULT_BYTES: raise HTTPException(413, "result zip too large")
                f.write(chunk)
        try:
            names = set(check_zip(tmp))
            with zipfile.ZipFile(tmp) as z:
                if z.testzip() is not None: raise ValueError("corrupt zip")
        except ValueError as e:
            raise HTTPException(422, str(e))
        for need in ("result/chant.wav", "result/result.json"):
            if need not in names: raise HTTPException(422, f"zip must contain {need}")
        os.replace(tmp, wd / "result_upload.zip")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return {"ok": True}
