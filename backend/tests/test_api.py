import json, os, shutil, subprocess, time
import pytest
from fastapi.testclient import TestClient

GITA = {"id": "bg-2-47", "text": ["कर्मण्येवाधिकारस्ते मा फलेषु कदाचन।", "मा कर्मफलहेतुर्भूर्मा ते सङ्गोऽस्त्वकर्मणि॥"],
        "source": {"work": "Bhagavad Gītā", "reference": "2.47"}}

@pytest.fixture()
def client(tmp_path, monkeypatch, pg, mem_storage):
    from backend.app import config as C
    monkeypatch.setattr(C, "STORAGE", tmp_path)
    monkeypatch.setattr(C, "SEED_FILE", tmp_path / "seed.json")
    from backend.app import main, queue
    monkeypatch.setattr(queue, "_started", False)
    with TestClient(main.app) as c:
        yield c

def wait(c, jid, want, t=15):
    for _ in range(t * 10):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in want: return j
        time.sleep(0.1)
    raise AssertionError(c.get(f"/api/jobs/{jid}").json())

def test_seed_rejects_missing_source(tmp_path):
    from backend.app import verses
    bad = dict(GITA, source={"work": "x"})
    with pytest.raises(verses.VerseError): verses.validate(bad)
    with pytest.raises(verses.VerseError): verses.validate(dict(GITA, text=[]))

def test_seed_rejects_duplicates(client, tmp_path):
    from backend.app import verses
    p = tmp_path / "s.json"; p.write_text(json.dumps([GITA, GITA]))
    with pytest.raises(verses.VerseError): verses.load_seed(p)

def test_verse_crud_and_duplicate(client):
    assert client.post("/api/verses", json=GITA).status_code == 201
    assert client.post("/api/verses", json=GITA).status_code == 409
    assert client.post("/api/verses", json=dict(GITA, id="z", source={"work": "", "reference": "1"})).status_code == 422
    v = client.get("/api/verses/bg-2-47").json()
    assert v["source"]["reference"] == "2.47" and len(v["text"]) == 2

def test_meter_suggest_gita(client):
    r = client.post("/api/meter-suggest", json={"text": GITA["text"]}).json()
    assert r["syllables_per_segment"] == [16, 16]
    assert r["meter"] == "anuṣṭubh" and r["exact"]

def test_job_lifecycle_with_fake_executor(client, monkeypatch, tmp_path):
    from backend.executors import local
    from backend.executors.base import Executor
    class Fake(Executor):
        name = "fake"
        def health(self): return {"ok": True}
        def run(self, spec, workdir, on_progress, is_cancelled):
            os.makedirs(workdir, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1", spec["out_wav"]], check=True)
            on_progress(0.5, "half"); return {"wav": spec["out_wav"], "duration": 1.0}
    class Boom(Fake):
        def run(self, *a, **k): raise RuntimeError("worker failed: boom")
    class Slow(Fake):
        def run(self, spec, workdir, on_progress, is_cancelled):
            from backend.executors.base import Cancelled
            for _ in range(100):
                if is_cancelled(): raise Cancelled()
                time.sleep(0.05)
    monkeypatch.setitem(local.REGISTRY, "fake", Fake); monkeypatch.setitem(local.REGISTRY, "boom", Boom)
    monkeypatch.setitem(local.REGISTRY, "slow", Slow)
    from backend.app import queue
    monkeypatch.setattr(queue, "_align", lambda *a, **k: None)   # alignment is tested separately
    client.post("/api/verses", json=GITA)
    mk = lambda ex: client.post("/api/jobs", json={"verse_id": "bg-2-47", "meter_id": "anushtubh", "executor": ex}).json()["id"]

    j = wait(client, mk("fake"), {"done", "failed"})
    assert j["status"] == "done" and j["asset"]["duration"] == 1.0
    assert client.get(f"/api/jobs/{j['id']}/audio.mp3").headers["content-type"] == "audio/mpeg"
    from backend.app import db, storage
    a = db.q1("SELECT * FROM assets WHERE job_id=?", (j["id"],))
    assert (a["mp3_key"], a["wav_key"], a["alignment_key"]) == (f"jobs/{j['id']}/chant.mp3", f"jobs/{j['id']}/chant.wav", None)
    assert storage.get().exists(a["mp3_key"]) and storage.get().exists(a["wav_key"])
    assert not (tmp_path / "jobs" / str(j["id"]) / "chant.mp3").exists()      # local scratch removed
    assert len(client.get("/api/verses").json()[0]["audio"]) == 1
    assert client.get(f"/api/jobs/{j['id']}/alignment").status_code == 404   # sine tone: no alignment, job still done

    j = wait(client, mk("boom"), {"done", "failed"})
    assert j["status"] == "failed" and "boom" in j["error"]

    jid = mk("slow"); wait(client, jid, {"running"})
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    assert wait(client, jid, {"cancelled", "done", "failed"})["status"] == "cancelled"

def test_bad_job_inputs(client):
    client.post("/api/verses", json=GITA)
    assert client.post("/api/jobs", json={"verse_id": "nope", "meter_id": "anushtubh"}).status_code == 404
    assert client.post("/api/jobs", json={"verse_id": "bg-2-47", "meter_id": "anushtubh", "executor": "ssh"}).status_code == 422


WAV = os.path.join(os.path.dirname(__file__), "..", "..", "POC", "outputs", "gita_2_47_default.wav")

@pytest.mark.skipif(not os.path.exists(WAV), reason="needs POC render + MMS_FA weights")
def test_alignment_gita_2_47():
    from backend.engine.align import align, validate
    from backend.engine.synth import syllable_counts
    padas = [l.rstrip("।॥") for l in GITA["text"]]
    al = align(WAV, padas, [p.split() for p in padas])
    assert validate(al, syllable_counts(padas)) == []
    assert [len(l["words"]) for l in al["lines"]] == [4, 4]
    assert al["lines"][0]["words"][0]["text"] == "कर्मण्येवाधिकारस्ते"
    assert sum(len(w["syllables"]) for l in al["lines"] for w in l["words"]) == 32


def test_shift_moves_all_times():
    from backend.engine.align import shift
    al = {"audio_duration": 1.0, "lines": [{"words": [{"start": 0.1, "end": 0.5, "syllables": [{"start": 0.1, "end": 0.5}]}]}]}
    shift(al, 0.4, 1.7)
    w = al["lines"][0]["words"][0]
    assert (w["start"], w["end"], w["syllables"][0]["start"], al["audio_duration"]) == (0.5, 0.9, 0.5, 1.7)


def _done_job_with_audio(client, mem_storage, data=bytes(range(256)) * 4):
    from backend.app import db, storage
    client.post("/api/verses", json=GITA)
    jid = db.q1("INSERT INTO jobs(verse_id,meter_id,voice_id,executor,device,steps,seed,status) "
                "VALUES('bg-2-47','anushtubh','steer','local','cpu',16,50,'done') RETURNING id")["id"]
    storage.get().put_bytes(f"jobs/{jid}/chant.mp3", data, "audio/mpeg")
    storage.get().put_bytes(f"jobs/{jid}/alignment.json", b'{"lines": []}', "application/json")
    db.x("INSERT INTO assets(job_id,mp3_key,alignment_key,duration) VALUES(?,?,?,?)",
         (jid, f"jobs/{jid}/chant.mp3", f"jobs/{jid}/alignment.json", 1.0))
    return jid, data


def test_audio_range_requests(client, mem_storage):
    jid, data = _done_job_with_audio(client, mem_storage)
    r = client.get(f"/api/jobs/{jid}/audio.mp3")
    assert r.status_code == 200 and r.content == data and r.headers["accept-ranges"] == "bytes"
    r = client.get(f"/api/jobs/{jid}/audio.mp3", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == data[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(data)}" and r.headers["content-type"] == "audio/mpeg"
    r = client.get(f"/api/jobs/{jid}/audio.mp3", headers={"Range": "bytes=1000-"})
    assert r.status_code == 206 and r.content == data[1000:]
    r = client.get(f"/api/jobs/{jid}/audio.mp3", headers={"Range": "bytes=-5"})
    assert r.content == data[-5:]
    assert client.get(f"/api/jobs/{jid}/audio.mp3", headers={"Range": "bytes=99999-"}).status_code == 416
    assert client.get(f"/api/jobs/{jid}/alignment").json() == {"lines": []}
    assert client.get("/api/jobs/9999/audio.mp3").status_code == 404


def test_missing_object_is_404(client, mem_storage):
    jid, _ = _done_job_with_audio(client, mem_storage)
    mem_storage.delete(f"jobs/{jid}/chant.mp3")
    assert client.get(f"/api/jobs/{jid}/audio.mp3").status_code == 404
