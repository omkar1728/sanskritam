import json, sqlite3
import pytest
from test_api import GITA  # noqa: F401

OLD = """
CREATE TABLE verses(id TEXT PRIMARY KEY, title TEXT, text TEXT, source_work TEXT, source_reference TEXT, source_url TEXT,
  source_edition TEXT, notes TEXT, meter_hint TEXT, origin TEXT, created_at TEXT);
CREATE TABLE jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, verse_id TEXT, meter_id TEXT, voice_id TEXT, executor TEXT, device TEXT,
  steps INT, seed INT, status TEXT, progress REAL, log TEXT, error TEXT, created_at TEXT, started_at TEXT, finished_at TEXT);
CREATE TABLE assets(job_id INTEGER PRIMARY KEY, mp3 TEXT, wav TEXT, alignment TEXT, duration REAL);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
"""


def test_import(pg, mem_storage, tmp_path):
    from backend.app import db, storage
    from backend.scripts import import_sqlite
    sq = tmp_path / "old" / "app.db"; sq.parent.mkdir()
    c = sqlite3.connect(sq); c.executescript(OLD)
    c.execute("INSERT INTO verses VALUES('1','T',?,'Work','1.1',NULL,NULL,NULL,NULL,'user','2026-01-02 03:04:05')",
              (json.dumps(GITA["text"], ensure_ascii=False),))
    c.execute("INSERT INTO jobs VALUES(7,'1','anushtubh','steer','local','cpu',16,50,'done',1,'log',NULL,'2026-01-02 03:04:05',NULL,NULL)")
    c.execute("INSERT INTO assets VALUES(7,NULL,NULL,NULL,2.5)")
    c.execute("INSERT INTO settings VALUES('steps','8')")
    c.commit(); c.close()
    d = sq.parent / "jobs" / "7"; d.mkdir(parents=True)
    (d / "chant.mp3").write_bytes(b"mp3"); (d / "chant.wav").write_bytes(b"wav"); (d / "alignment.json").write_text("{}")
    dm = tmp_path / "dm.json"
    dm.write_text(json.dumps({"origin": "machine", "reviewed": False,
        "words": [dict(line=0, index=1, text="मा", meaning="not")], "summary": {"translation": "T"}}))
    for _ in range(2):                       # re-runnable
        cnt = import_sqlite.run(sq, dm)
    assert cnt["jobs"] == 1 and cnt["files"] == 3
    assert db.q1("SELECT count(*) n FROM verses WHERE id='1'")["n"] == 1
    a = db.q1("SELECT * FROM assets WHERE job_id=7")
    assert (a["mp3_key"], a["wav_key"], a["alignment_key"], a["duration"]) == ("jobs/7/chant.mp3", "jobs/7/chant.wav", "jobs/7/alignment.json", 2.5)
    assert storage.get().read_bytes("jobs/7/chant.mp3") == b"mp3"
    assert db.get_settings()["steps"] == "8"
    new = db.q1("INSERT INTO jobs(verse_id,meter_id,voice_id,executor,device,steps,seed) VALUES('1','anushtubh','steer','local','cpu',1,1) RETURNING id")
    assert new["id"] == 8                    # sequence advanced past imported ids
    from backend.app import verses
    m = verses.get_meanings("1")
    assert m["words"][0]["origin"] == "machine" and m["words"][0]["reviewed"] is False and m["summary"]["translation"] == "T"
