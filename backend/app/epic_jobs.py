"""Epic audio batches: materialise epic_verses into verses, create awaiting_result jobs for a Colab batch run."""
import json
from . import db, verses
from backend.engine.meter import suggest

MAX_BATCH_JOBS = 2000
WORK = "Valmiki Ramayana"
ED_CRIT = "Baroda Critical Edition via Smith (bombay.indology.info)"
ED_VULG = "valmikiramayan.net vulgate"

class BatchError(ValueError): ...

def _lines(v):
    if isinstance(v, str): v = v.splitlines()
    if not isinstance(v, list): return None
    out = [l.strip() for l in v if isinstance(l, str) and l.strip()]
    return out or None

def _j(v):
    return v

def _candidate(r) -> dict | None:
    """Verse row dict (not inserted) from an epic_verses row; None when no text exists. Never invents text."""
    text = _lines(_j(r["pd"])) or _lines(_j(r["cl"]))
    crit = text is not None
    if not crit:
        text = _lines(_j(r["vl"]))
    if not text: return None
    refs = _j(r["refs"]) or {}
    cs = refs.get("critical_smith") or {}
    if crit and cs.get("sarga") is not None and cs.get("verse") is not None:
        ref = f"{r['kanda']}.{cs['sarga']}.{cs['verse']}"
    else:
        ref = f"{r['kanda']}.{r['sarga']}.{r['seq']}"
    return {"id": f"ramayana-{r['id']}", "title": f"Ramayana {ref}", "text": text,
            "source": {"work": WORK, "reference": ref, "url": None, "edition": ED_CRIT if crit else ED_VULG},
            "ref": ref}

def _select(b):
    if b.epic != "ramayana": raise BatchError("only ramayana is supported")
    sql = ("SELECT id,kanda,sarga,seq, data->'refs' refs, data#>'{text,critical_smith,punctuated_derived}' pd,"
           " data#>'{text,critical_smith,lines}' cl, data#>'{text,vulgate_net,lines}' vl FROM epic_verses WHERE epic=?")
    args = [b.epic]
    if b.verse_id:
        vid = b.verse_id[len("ramayana-"):] if b.verse_id.startswith("ramayana-") else b.verse_id
        sql += " AND id=?"; args.append(vid)
    else:
        if b.kanda is None and b.sarga is not None: raise BatchError("sarga needs kanda")
        if b.kanda is not None: sql += " AND kanda=?"; args.append(b.kanda)
        if b.sarga is not None: sql += " AND sarga=?"; args.append(b.sarga)
    return db.q(sql + " ORDER BY kanda, sarga, seq", tuple(args))

def _check(b):
    if not db.q1("SELECT 1 FROM voices WHERE id=? AND enabled", (b.voice_id,)): raise BatchError(f"unknown voice '{b.voice_id}'")
    if b.meter_id and not db.q1("SELECT 1 FROM meters WHERE id=?", (b.meter_id,)): raise BatchError(f"unknown meter '{b.meter_id}'")

def plan(b) -> dict:
    _check(b)
    meters = [dict(m) for m in db.q("SELECT * FROM meters")]
    done = {(r["verse_id"], r["meter_id"]) for r in
            db.q("SELECT verse_id, meter_id FROM jobs WHERE status='done' AND voice_id=? AND steps=? AND verse_id LIKE 'ramayana-%'",
                 (b.voice_id, b.steps))}
    todo, skipped, unavailable = [], 0, []
    for r in _select(b):
        c = _candidate(r)
        if not c: unavailable.append(f"ramayana-{r['id']}"); continue
        if b.meter_id: mid = b.meter_id
        else:
            s = suggest(verses.padas(c["text"]), meters)
            if not s: unavailable.append(c["id"]); continue
            mid = s["meter_id"]
        c["meter_id"] = mid
        if (c["id"], mid) in done: skipped += 1
        else: todo.append(c)
    return {"todo": todo, "skipped": skipped, "unavailable": unavailable}

def preview(b) -> dict:
    p = plan(b); todo = p["todo"]
    counts: dict = {}
    for c in todo: counts[c["meter_id"]] = counts.get(c["meter_id"], 0) + 1
    return {"total": len(todo) + p["skipped"] + len(p["unavailable"]), "to_generate": len(todo), "skipped": p["skipped"],
            "unavailable": len(p["unavailable"]), "unavailable_ids": p["unavailable"][:20],
            "meters": [{"meter_id": m, "count": n} for m, n in sorted(counts.items(), key=lambda t: -t[1])],
            "sample": [{"id": c["id"], "ref": c["ref"], "meter_id": c["meter_id"]} for c in todo[:20]]}

def create(b) -> dict:
    p = plan(b); todo = p["todo"]
    if not todo: raise BatchError("nothing to generate")
    if len(todo) > MAX_BATCH_JOBS:
        raise BatchError(f"{len(todo)} jobs exceeds the per-batch cap of {MAX_BATCH_JOBS}; choose a smaller scope")
    scope = {"kanda": b.kanda, "sarga": b.sarga, "verse_id": b.verse_id, "meter_id": b.meter_id}
    with db.tx():
        existing = {r["id"] for r in db.q("SELECT id FROM verses WHERE id=ANY(?)", ([c["id"] for c in todo],))}
        for c in todo:
            if c["id"] not in existing:
                verses.insert({"id": c["id"], "title": c["title"], "text": c["text"], "source": c["source"]}, "seed")
        bid = db.q1("INSERT INTO epic_batches(epic,scope,voice_id,steps,seed,device) VALUES(?,?::jsonb,?,?,?,?) RETURNING id",
                    (b.epic, json.dumps(scope), b.voice_id, b.steps, b.seed, b.device))["id"]
        ids = [db.q1("INSERT INTO jobs(verse_id,meter_id,voice_id,executor,device,steps,seed,status,batch_id)"
                     " VALUES(?,?,?,'colab_batch',?,?,?,'awaiting_result',?) RETURNING id",
                     (c["id"], c["meter_id"], b.voice_id, b.device, b.steps, b.seed, bid))["id"] for c in todo]
    return {"batch_id": bid, "job_ids": ids, "count": len(ids)}

def list_batches() -> list:
    out = []
    for r in db.q("SELECT * FROM epic_batches ORDER BY id DESC"):
        r["counts"] = {x["status"]: x["n"] for x in
                       db.q("SELECT status, count(*) n FROM jobs WHERE batch_id=? GROUP BY status", (r["id"],))}
        out.append(r)
    return out

def get_batch(bid: int):
    r = db.q1("SELECT * FROM epic_batches WHERE id=?", (bid,))
    if not r: return None
    r["jobs"] = db.q("SELECT id,verse_id,status,progress,error FROM jobs WHERE batch_id=? ORDER BY id", (bid,))
    r["counts"] = {}
    for j in r["jobs"]: r["counts"][j["status"]] = r["counts"].get(j["status"], 0) + 1
    return r
