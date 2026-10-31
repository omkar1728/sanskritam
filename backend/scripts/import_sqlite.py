"""One-off, re-runnable import of the old SQLite app.db into Postgres + object storage.

  uv run python -m backend.scripts.import_sqlite --sqlite backend/storage/app.db [--dev-meanings backend/seed/dev_meanings_2_47.json]

Jobs keep their ids (the identity sequence is advanced). Each job's chant.mp3/chant.wav/alignment.json from
<sqlite dir>/jobs/<id>/ is uploaded under jobs/<id>/ and the keys are stored in assets.
"""
import argparse, json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
from backend.app import db, queue, storage, verses

def _ts(s):
    if not s: return None
    d = datetime.fromisoformat(str(s))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)      # SQLite CURRENT_TIMESTAMP is UTC

def run(sqlite_path, dev_meanings=None, jobs_dir=None) -> dict:
    sqlite_path = Path(sqlite_path)
    jobs_dir = Path(jobs_dir) if jobs_dir else sqlite_path.parent / "jobs"
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True); src.row_factory = sqlite3.Row
    cnt = dict(verses=0, jobs=0, assets=0, settings=0, files=0)
    db.init()
    st = storage.get()
    with db.tx():
        for r in src.execute("SELECT * FROM verses"):
            text = r["text"] if isinstance(r["text"], str) else json.dumps(r["text"])
            db.x("INSERT INTO verses(id,title,text,source_work,source_reference,source_url,source_edition,notes,meter_hint,origin,created_at)"
                 " VALUES(?,?,?::jsonb,?,?,?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING",
                 (r["id"], r["title"], text, r["source_work"], r["source_reference"], r["source_url"], r["source_edition"],
                  r["notes"], r["meter_hint"], r["origin"], _ts(r["created_at"]) or datetime.now(timezone.utc)))
            cnt["verses"] += 1
        for r in src.execute("SELECT * FROM jobs ORDER BY id"):
            db.x("INSERT INTO jobs(id,verse_id,meter_id,voice_id,executor,device,steps,seed,status,progress,log,error,"
                 "created_at,started_at,finished_at) OVERRIDING SYSTEM VALUE VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                 " ON CONFLICT (id) DO NOTHING",
                 (r["id"], r["verse_id"], r["meter_id"], r["voice_id"], r["executor"], r["device"], r["steps"], r["seed"],
                  r["status"], r["progress"], r["log"], r["error"], _ts(r["created_at"]), _ts(r["started_at"]), _ts(r["finished_at"])))
            cnt["jobs"] += 1
        db.x("SELECT setval(pg_get_serial_sequence('jobs','id'), greatest((SELECT coalesce(max(id),0) FROM jobs), 1))")
        for r in src.execute("SELECT * FROM settings"):
            db.set_setting(r["key"], r["value"]); cnt["settings"] += 1
    for r in src.execute("SELECT * FROM assets ORDER BY job_id"):
        jid, d = r["job_id"], jobs_dir / str(r["job_id"])
        keys = {}
        for field, name, ct in (("mp3", "chant.mp3", "audio/mpeg"), ("wav", "chant.wav", "audio/wav"),
                                ("alignment", "alignment.json", "application/json")):
            p = Path(r[field]) if r[field] and Path(r[field]).exists() else d / name
            if p.exists():
                st.put_file(queue.key(jid, name), str(p), ct); keys[field] = queue.key(jid, name); cnt["files"] += 1
            else:
                keys[field] = None
        db.x("INSERT INTO assets(job_id,mp3_key,wav_key,alignment_key,duration) VALUES(?,?,?,?,?) ON CONFLICT (job_id) DO UPDATE"
             " SET mp3_key=EXCLUDED.mp3_key, wav_key=EXCLUDED.wav_key, alignment_key=EXCLUDED.alignment_key, duration=EXCLUDED.duration",
             (jid, keys["mp3"], keys["wav"], keys["alignment"], r["duration"]))
        cnt["assets"] += 1
    if dev_meanings:
        m = json.loads(Path(dev_meanings).read_text(encoding="utf-8"))
        verses.set_meanings("1", m.get("words", []), m.get("summary"), m.get("origin", "machine"), bool(m.get("reviewed", False)))
        cnt["dev_meanings_words"] = len(m.get("words", []))
    return cnt

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", required=True); ap.add_argument("--dev-meanings"); ap.add_argument("--jobs-dir")
    a = ap.parse_args(argv)
    try:
        storage.get().ensure_bucket()
        print(run(a.sqlite, a.dev_meanings, a.jobs_dir))
    except (KeyError, verses.MeaningsError) as e:
        sys.exit(f"import failed: {e!r}")

if __name__ == "__main__":
    main()
