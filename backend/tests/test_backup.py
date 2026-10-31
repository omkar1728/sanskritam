import json, sqlite3, time
import pytest
from fastapi.testclient import TestClient

V = {"id": "fx-1", "text": ["fixture line one", "fixture line two"], "source": {"work": "FIXTURE", "reference": "0.0"}}

@pytest.fixture()
def env(tmp_path, monkeypatch, pg, mem_storage):
    from backend.app import config as C, db, backup
    monkeypatch.setattr(C, "BACKUP_SQLITE_PATH", tmp_path / "bk" / "m.sqlite")
    monkeypatch.setattr(C, "BACKUP_KEEP", 3)
    monkeypatch.setattr(C, "BACKUP_INTERVAL_S", 0.1)
    monkeypatch.setattr(C, "SEED_FILE", tmp_path / "none.json")
    monkeypatch.setattr(backup, "_mirror", backup.Mirror())
    db.init()
    return tmp_path

def seed_data():
    from backend.app import db, verses
    verses.insert(dict(V), "user")
    verses.set_meanings("fx-1", [{"line": 0, "index": 0, "text": "fixture", "meaning": "m1", "grammar": None}],
                        {"translation": "tr", "explanation": None}, "user", True)
    db.x("INSERT INTO jobs(verse_id,meter_id,voice_id,executor,device,steps,seed,status) VALUES('fx-1','m','steer','local','cpu',4,1,'done')")
    jid = db.q1("SELECT max(id) i FROM jobs")["i"]
    db.x("INSERT INTO assets(job_id,mp3_key,duration) VALUES(?,?,?)", (jid, f"jobs/{jid}/chant.mp3", 1.5))
    return jid

def files(env): return sorted((env / "bk").glob("*.sqlite"))
def rows(path, sql):
    c = sqlite3.connect(path)
    try: return c.execute(sql).fetchall()
    finally: c.close()

def test_snapshot_matches_postgres(env):
    from backend.app import backup, db
    jid = seed_data()
    st = backup.get().backup_now()
    assert st["last_error"] is None and st["rows"]["verses"] == 1
    p = env / "bk" / "m.sqlite"
    assert rows(p, "SELECT id, title, text FROM verses")[0][0] == "fx-1"
    assert json.loads(rows(p, "SELECT text FROM verses")[0][0]) == V["text"]
    assert rows(p, "SELECT word_text, meaning FROM word_meanings") == [("fixture", "m1")]
    assert rows(p, "SELECT translation, reviewed FROM verse_summaries") == [("tr", 1)]
    assert rows(p, "SELECT id, status, steps FROM jobs") == [(jid, "done", 4)]
    assert rows(p, "SELECT job_id, mp3_key, duration FROM assets") == [(jid, f"jobs/{jid}/chant.mp3", 1.5)]
    assert rows(p, "SELECT count(*) FROM meters")[0][0] == db.q1("SELECT count(*) n FROM meters")["n"]
    assert rows(p, "SELECT count(*) FROM settings")[0][0] == len(db.get_settings())
    assert json.loads(dict(rows(p, "SELECT key,value FROM _meta"))["row_counts"])["jobs"] == 1

def test_unchanged_no_new_generation_changed_one(env):
    from backend.app import backup, db
    seed_data(); m = backup.get()
    m.backup_now(); assert len(files(env)) == 1
    m.backup_now(); m.backup_now(); assert len(files(env)) == 1
    db.set_setting("steps", "9")
    m.backup_now(); assert len(files(env)) == 2
    assert rows(env / "bk" / "m.sqlite", "SELECT value FROM settings WHERE key='steps'") == [("9",)]

def test_rotation_keeps_n(env):
    from backend.app import backup, db
    m = backup.get()
    for i in range(8):
        db.set_setting("steps", str(i)); m.backup_now(); time.sleep(0.002)
    assert len(files(env)) == 1 + 3 and m.status()["generations"] == 3

def test_failure_keeps_previous_good_file(env, monkeypatch):
    from backend.app import backup, db
    m = backup.get(); m.backup_now()
    p = env / "bk" / "m.sqlite"; before = p.read_bytes()
    db.set_setting("steps", "77")
    def boom(snap, path, fp):
        path.write_bytes(b"half"); raise OSError("disk full")
    monkeypatch.setattr(backup, "write_sqlite", boom)
    st = m.backup_now()
    assert "disk full" in st["last_error"] and p.read_bytes() == before and len(files(env)) == 1
    assert not list((env / "bk").glob(".*"))

def test_background_thread_and_stop(env):
    from backend.app import backup
    m = backup.get(); m.start(force=True)
    for _ in range(50):
        if m.last_success_at: break
        time.sleep(0.1)
    assert m.last_success_at and m.status()["running"]
    m.stop(); assert not m.status()["running"]

def test_restore_round_trip(env, monkeypatch):
    import psycopg
    from backend.app import backup, db, config as C
    from backend.scripts import restore_from_sqlite as R
    jid = seed_data(); backup.get().backup_now()
    order = {"verses": "id", "meters": "id", "voices": "id", "jobs": "id", "assets": "job_id", "settings": "key",
             "word_meanings": "verse_id,line_idx,word_idx", "verse_summaries": "verse_id"}
    orig = {t: [dict(r) for r in db.q(f"SELECT * FROM {t} ORDER BY {o}")] for t, o in order.items()}
    # new empty schema
    schema2 = db.search_path + "_r"
    with psycopg.connect(C.DATABASE_URL, autocommit=True) as a: a.execute(f"CREATE SCHEMA {schema2}")
    try:
        monkeypatch.setattr(db, "search_path", schema2); db.reset_connection()
        R.main(["--sqlite", str(env / "bk" / "m.sqlite")])
        for t, o in order.items():
            assert [dict(r) for r in db.q(f"SELECT * FROM {t} ORDER BY {o}")] == orig[t], t
        db.x("INSERT INTO jobs(verse_id,meter_id,voice_id,executor,device,steps,seed) VALUES('fx-1','m','steer','local','cpu',4,1)")
        assert db.q1("SELECT max(id) i FROM jobs")["i"] == jid + 1
        with pytest.raises(SystemExit) as e: R.main(["--sqlite", str(env / "bk" / "m.sqlite")])
        assert "not empty" in str(e.value)
        R.main(["--sqlite", str(env / "bk" / "m.sqlite"), "--yes"])
        assert db.q1("SELECT count(*) n FROM jobs")["n"] == 1
    finally:
        db.reset_connection()
        with psycopg.connect(C.DATABASE_URL, autocommit=True) as a: a.execute(f"DROP SCHEMA {schema2} CASCADE")

def test_restore_rejects_bad_file(env, tmp_path):
    from backend.scripts import restore_from_sqlite as R
    p = tmp_path / "x.sqlite"; sqlite3.connect(p).execute("CREATE TABLE t(a)").connection.commit()
    with pytest.raises(SystemExit): R.main(["--sqlite", str(p)])

def test_endpoints(env):
    from backend.app import main
    c = TestClient(main.app)       # no lifespan: no worker thread
    assert c.get("/api/backup").json()["last_success_at"] is None
    seed_data()
    r = c.post("/api/backup"); assert r.status_code == 200
    j = r.json(); assert j["rows"]["verses"] == 1 and j["last_error"] is None and j["last_fingerprint"]
    assert c.get("/api/backup").json()["last_fingerprint"] == j["last_fingerprint"]
