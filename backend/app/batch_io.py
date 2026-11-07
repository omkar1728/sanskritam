"""Batch hand-off files: input.zip (for the Colab batch worker) and results.zip ingestion."""
import hashlib, json, math, re, shutil, tempfile, zipfile
from pathlib import Path
from . import config as C, db, verses

MAX_RESULTS_BYTES = 2 * 1024 * 1024 * 1024

class BatchIOError(ValueError): ...

def _jobs_dir(jid: int) -> Path:
    return C.STORAGE / "jobs" / str(jid)

BACKEND_DIR = Path(__file__).resolve().parents[1]
_CODE_DIRS = ("engine", "executors", "worker")          # whole packages the Colab worker needs
_CODE_FILES = ("__init__.py", "app/__init__.py", "app/config.py")   # config is imported by engine.*

def code_files() -> list[tuple[str, Path]]:
    """(relative posix path under backend/, file) for the code shipped to Colab. Deterministic order."""
    out = {}
    for rel in _CODE_FILES:
        f = BACKEND_DIR / rel
        if f.is_file(): out[rel] = f
    for d in _CODE_DIRS:
        for f in (BACKEND_DIR / d).rglob("*"):
            r = f.relative_to(BACKEND_DIR)
            if (not f.is_file() or "__pycache__" in r.parts or f.suffix in (".pyc", ".db", ".sqlite")
                    or f.name.startswith(".env")): continue
            out[r.as_posix()] = f
    return sorted(out.items())

def code_version() -> str:
    h = hashlib.sha1()
    for rel, f in code_files(): h.update(rel.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:12]

RESULTS_ROOT = "batch_results"
_VID = re.compile(r"^(?:ramayana-)?([a-z]+)-(\d{1,3})-(\d{1,4})$")

def batch_dir_for(bid: int) -> str:
    return f"{RESULTS_ROOT}/_batches/{int(bid)}"

def result_dir_for(verse_id: str) -> str:
    """Relative POSIX result folder for a verse id ('ramayana-baala-001-001' or 'baala-001-001')."""
    m = _VID.match(verse_id or "")
    if not m: raise BatchIOError(f"cannot build a result path for verse id {verse_id!r}")
    key, sarga = m.group(1), int(m.group(2))
    return f"{RESULTS_ROOT}/ramayana/{key}/sarga_{sarga:03d}/{key}-{m.group(2)}-{m.group(3)}"

def build_input_zip(bid: int) -> Path:
    from backend.executors.bundle import zip_dir
    rows = db.q("SELECT * FROM jobs WHERE batch_id=? AND status='awaiting_result' ORDER BY id", (bid,))
    if not rows: raise BatchIOError("batch has no jobs awaiting a result")
    root = C.STORAGE / "batches" / str(bid); build = root / "build"
    shutil.rmtree(build, ignore_errors=True); (build / "refs").mkdir(parents=True)
    meters, voices, jobs = {}, {}, []
    for j in rows:
        m = meters.get(j["meter_id"]) or meters.setdefault(j["meter_id"], db.q1("SELECT * FROM meters WHERE id=?", (j["meter_id"],)))
        vo = voices.get(j["voice_id"]) or voices.setdefault(j["voice_id"], db.q1("SELECT * FROM voices WHERE id=?", (j["voice_id"],)))
        ref = build / "refs" / f"{m['id']}.wav"
        if not ref.exists(): shutil.copyfile(m["wav"], ref)
        v = verses.present(db.q1("SELECT * FROM verses WHERE id=?", (j["verse_id"],)))
        jobs.append({"job_id": j["id"], "verse_id": j["verse_id"], "result_dir": result_dir_for(j["verse_id"]), "spec": {
            "padas": verses.padas(v["text"]), "ref_wav": f"refs/{m['id']}.wav", "ref_text": m["ref_text"],
            "sec_per_syll": m["sec_per_syll"], "voice_ckpt": "models/" + Path(vo["checkpoint"]).name,
            "vocoder_ckpt": "models/" + Path(vo["vocoder"]).name, "steps": j["steps"], "seed": j["seed"], "device": j["device"]}})
    for rel, f in code_files():
        dst = build / "code" / "backend" / rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(f, dst)
    (build / "batch.json").write_text(json.dumps({"batch_id": bid, "code_version": code_version(), "results_root": RESULTS_ROOT,
                                                  "batch_dir": batch_dir_for(bid), "jobs": jobs}, ensure_ascii=False, indent=1), encoding="utf-8")
    out = root / "batch.zip"
    zip_dir(build, out)
    shutil.rmtree(build, ignore_errors=True)
    return out

def _int_id(s: str):
    return int(s) if s.isascii() and s.isdigit() and str(int(s)) == s else None

def _valid_info(raw: bytes):
    """Parsed result.json or None when unusable."""
    try:
        info = json.loads(raw.decode("utf-8"))
        if not isinstance(info, dict): return None
        dur = float(info["duration"])
        return info if math.isfinite(dur) and dur > 0 else None
    except (ValueError, KeyError, TypeError, UnicodeDecodeError): return None

def _stage(bid: int, i: int, open_wav, info: dict) -> bool:
    """Copy the wav + result.json into job_dir/staged and requeue the job. True if the job was accepted."""
    sd = _jobs_dir(i) / "staged"
    shutil.rmtree(sd, ignore_errors=True); sd.mkdir(parents=True)
    with open_wav() as src, open(sd / "chant.wav", "wb") as dst: shutil.copyfileobj(src, dst)
    (sd / "result.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    cur = db.x("UPDATE jobs SET executor='colab_staged', status='queued', progress=0, error=NULL WHERE id=? AND batch_id=?"
               " AND status='awaiting_result'", (i, bid))
    if cur.rowcount: return True
    shutil.rmtree(sd, ignore_errors=True); return False

def _fail(bid: int, i: int, msg) -> bool:
    cur = db.x("UPDATE jobs SET status='failed', error=?, finished_at=CURRENT_TIMESTAMP WHERE id=? AND batch_id=?"
               " AND status='awaiting_result'", (str(msg)[-4000:], i, bid))
    return bool(cur.rowcount)

def ingest_drive(bid: int, base: Path) -> dict:
    """Stage results found in a (Drive-synced) folder. Paths come from the DB, never from file contents."""
    base = Path(base).resolve()
    jobs = db.q("SELECT id, verse_id FROM jobs WHERE batch_id=? AND status='awaiting_result' ORDER BY id", (bid,))
    def safe(p: Path):
        try: r = p.resolve()
        except (OSError, RuntimeError): return None
        return r if r.is_relative_to(base) and r.is_file() else None
    errors = {}
    ef = safe(base / batch_dir_for(bid) / "errors.json")
    if ef:
        try:
            e = json.loads(ef.read_text(encoding="utf-8")); errors = e if isinstance(e, dict) else {}
        except (ValueError, OSError): pass
    accepted = failed = ignored = missing = 0
    for j in jobs:
        i = j["id"]
        try: d = base / result_dir_for(j["verse_id"])
        except BatchIOError: ignored += 1; continue
        wav, rj = safe(d / "chant.wav"), safe(d / "result.json")
        if wav and rj:
            try: info = _valid_info(rj.read_bytes())
            except OSError: info = None
            if info is None: ignored += 1; continue
            try: ok = _stage(bid, i, lambda w=wav: open(w, "rb"), info)
            except OSError: ok = False
            if ok: accepted += 1
            else: ignored += 1
        elif str(i) in errors or i in errors:
            if _fail(bid, i, errors.get(str(i), errors.get(i))): failed += 1
            else: ignored += 1
        else: missing += 1
    from . import queue
    queue._wake.set()
    return {"accepted": accepted, "failed": failed, "ignored": ignored, "missing": missing}

def ingest_results(bid: int, zpath) -> dict:
    """Stage uploaded results. Returns {accepted, failed, ignored}; raises ValueError for a bad zip."""
    from backend.executors.bundle import check_zip
    names = set(check_zip(zpath))
    with zipfile.ZipFile(zpath) as z:
        if z.testzip() is not None: raise ValueError("corrupt zip")
        waiting = {r["id"] for r in db.q("SELECT id FROM jobs WHERE batch_id=? AND status='awaiting_result'", (bid,))}
        # the Colab notebook zips "results/<job_id>/..."; a bare "<job_id>/..." layout is accepted too
        pre = "results/" if any(n.startswith("results/") for n in names) else ""
        rel = {n[len(pre):] for n in names if n.startswith(pre)}
        tops = {n.split("/", 1)[0] for n in rel if n.split("/", 1)[0]}
        cand = set()
        for t in tops:
            i = _int_id(t)
            if i is not None: cand.add(i)
        errors = {}
        if "errors.json" in rel:
            try:
                e = json.loads(z.read(pre + "errors.json").decode("utf-8"))
                errors = e if isinstance(e, dict) else {}
            except ValueError: pass
        accepted = failed = ignored = 0
        done_ids, failed_ids = set(), set()
        for i in sorted(cand):
            if i not in waiting or f"{i}/chant.wav" not in rel or f"{i}/result.json" not in rel:
                continue
            try:
                info = json.loads(z.read(f"{pre}{i}/result.json").decode("utf-8"))
                dur = float(info["duration"])
                if not isinstance(info, dict) or not math.isfinite(dur) or dur <= 0: raise ValueError
            except (ValueError, KeyError, TypeError):
                continue
            def _open(i=i): return z.open(f"{pre}{i}/chant.wav")
            if _stage(bid, i, _open, info): accepted += 1; done_ids.add(i)
        for k, msg in errors.items():
            i = _int_id(str(k))
            if i is None or i not in waiting or i in done_ids: continue
            if _fail(bid, i, msg): failed += 1; failed_ids.add(i)
        bad_err = {k for k in errors if _int_id(str(k)) not in failed_ids and _int_id(str(k)) not in done_ids}
        ignored = len(bad_err | {str(i) for i in cand - done_ids - failed_ids})
    from . import queue
    queue._wake.set()
    return {"accepted": accepted, "failed": failed, "ignored": ignored}

def ingest_any(zpath) -> dict:
    """Ingest a results zip without being told the batch: the batch(es) are found from the job ids inside it.
    Returns {accepted, failed, ignored, batches, job_ids}; raises ValueError if the zip matches no waiting job."""
    from backend.executors.bundle import check_zip
    names = check_zip(zpath)
    ids = set()
    for n in names:
        parts = [p for p in n.replace("\\", "/").split("/") if p]
        if parts and parts[0] == "results": parts = parts[1:]
        if len(parts) > 1 and _int_id(parts[0]) is not None: ids.add(int(parts[0]))
    with zipfile.ZipFile(zpath) as z:
        for n in names:
            if n.rstrip("/").split("/")[-1] == "errors.json":
                try:
                    e = json.loads(z.read(n).decode("utf-8"))
                    ids |= {int(k) for k in (e if isinstance(e, dict) else {}) if _int_id(str(k)) is not None}
                except ValueError: pass
    rows = []
    if ids:
        ph = ",".join("?" * len(ids))
        rows = db.q(f"SELECT id, batch_id FROM jobs WHERE status='awaiting_result' AND batch_id IS NOT NULL AND id IN ({ph})", tuple(sorted(ids)))
    if not rows: raise ValueError("no job in this zip is waiting for a result (already uploaded, or from another database?)")
    batches = sorted({r["batch_id"] for r in rows})
    tot = {"accepted": 0, "failed": 0, "ignored": 0}
    for b in batches:
        r = ingest_results(b, zpath)
        for k in tot: tot[k] += r[k]
    tot["ignored"] += len(ids) - len(rows)
    return {**tot, "batches": batches, "job_ids": sorted(r["id"] for r in rows)}
