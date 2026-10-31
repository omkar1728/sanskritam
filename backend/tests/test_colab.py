import io, json, sys, math, threading, time, wave, zipfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.executors import bundle as B
from backend.executors.base import Cancelled
from backend.worker import colab_worker as W
from test_api import client, wait, GITA  # noqa: F401


def sine(path, secs=0.3):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(b"".join(int(8000 * math.sin(i / 10)).to_bytes(2, "little", signed=True) for i in range(int(8000 * secs))))


def fake_render(spec, progress):
    assert Path(spec["voice_ckpt"]).name == "v.pt" and Path(spec["ref_wav"]).exists()
    progress(0, 2, "a"); time.sleep(0.1); progress(1, 2, "b")
    sine(spec["out_wav"])
    return {"duration": 0.3, "pada_spans": [[0, 0.3]], "syllables": [4]}


@pytest.fixture()
def spec(tmp_path):
    sine(tmp_path / "ref_src.wav")
    return dict(padas=["x"], ref_wav=str(tmp_path / "ref_src.wav"), ref_text="t", sec_per_syll=0.5,
                voice_ckpt="/abs/dir/v.pt", vocoder_ckpt="/abs/dir/voc.pth", out_wav="/abs/out/chant.wav", steps=4, seed=1)


def test_bundle_round_trip(tmp_path, spec):
    B.make_bundle(spec, tmp_path / "b")
    s = json.loads((tmp_path / "b" / "spec.json").read_text())
    assert (s["ref_wav"], s["voice_ckpt"], s["vocoder_ckpt"], s["out_wav"]) == ("ref.wav", "models/v.pt", "models/voc.pth", "result/chant.wav")
    assert s["steps"] == 4 and (tmp_path / "b" / "ref.wav").exists()
    r = B.resolve_spec(tmp_path / "b", tmp_path / "M")
    assert r["voice_ckpt"] == str(tmp_path / "M" / "v.pt") and r["out_wav"] == str(tmp_path / "b" / "result" / "chant.wav")
    z = B.zip_dir(tmp_path / "b", tmp_path / "b.zip")
    B.unzip_safe(z, tmp_path / "u")
    assert (tmp_path / "u" / "spec.json").exists()


def test_unzip_rejects_traversal_and_size(tmp_path):
    for name in ("../evil.txt", "/abs.txt"):
        p = tmp_path / "bad.zip"
        with zipfile.ZipFile(p, "w") as z: z.writestr(name, "x")
        with pytest.raises(ValueError): B.unzip_safe(p, tmp_path / "o")
    p = tmp_path / "big.zip"
    with zipfile.ZipFile(p, "w") as z: z.writestr("a", b"0" * 5000)
    with pytest.raises(ValueError): B.unzip_safe(p, tmp_path / "o", max_bytes=100)
    assert not (tmp_path / "evil.txt").exists()


@pytest.fixture()
def drive(tmp_path, monkeypatch, client):
    from backend.app import db
    from backend.executors.drive import DriveExecutor
    root = tmp_path / "drive"; (root / "models").mkdir(parents=True)
    for f in ("vocab.txt", "v.pt", "voc.pth"): (root / "models" / f).write_text("x")
    db.set_setting("colab_drive_dir", str(root))
    monkeypatch.setattr(DriveExecutor, "poll_s", 0.05); monkeypatch.setattr(DriveExecutor, "sync_check_s", 0.05)
    stop = threading.Event()
    def start_worker(render=fake_render):
        t = threading.Thread(target=W.serve, args=(root, root / "models", render),
                             kwargs=dict(poll_s=0.05, stop=stop), daemon=True); t.start()
    yield root, start_worker, DriveExecutor()
    stop.set()


def test_drive_health(drive, tmp_path):
    root, _, ex = drive
    assert ex.health()["ok"]
    (root / "models" / "vocab.txt").unlink()
    h = ex.health(); assert not h["ok"] and "vocab.txt" in h["detail"]


def test_drive_end_to_end(drive, tmp_path, spec):
    root, start, ex = drive
    start()
    prog = []
    wd = tmp_path / "wd" / "7"
    res = ex.run(spec, str(wd), lambda p, m: prog.append((p, m)), lambda: False)
    assert Path(res["wav"]).exists() and res["duration"] == 0.3 and res["syllables"] == [4]
    jd = next((root / "jobs").iterdir())
    assert jd.name.endswith("-job7") and (jd / "DONE").exists() and (jd / "CLAIMED").exists()
    assert any(0 <= p <= 1 for p, _ in prog)


def test_drive_failed(drive, tmp_path, spec):
    root, start, ex = drive
    def boom(spec, progress): raise ValueError("kaboom")
    start(boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        ex.run(spec, str(tmp_path / "wd" / "1"), lambda p, m: None, lambda: False)


def test_drive_timeout(drive, tmp_path, spec):
    from backend.app import db
    db.set_setting("colab_timeout_s", "0.3")   # no worker running
    with pytest.raises(RuntimeError, match="notebook running"):
        drive[2].run(spec, str(tmp_path / "wd" / "1"), lambda p, m: None, lambda: False)


def test_drive_cancel(drive, tmp_path, spec):
    root, _, ex = drive
    t0 = time.time()
    with pytest.raises(Cancelled):
        ex.run(spec, str(tmp_path / "wd" / "1"), lambda p, m: None, lambda: time.time() - t0 > 0.3)
    assert (next((root / "jobs").iterdir()) / "CANCEL").exists()


def test_worker_honours_cancel_and_bundle_mode(tmp_path, spec):
    B.make_bundle(spec, tmp_path / "jb")
    (tmp_path / "jb" / "CANCEL").write_text("c")
    W.process_job(tmp_path / "jb", tmp_path / "M", fake_render)
    assert (tmp_path / "jb" / "FAILED").exists()
    B.make_bundle(spec, tmp_path / "man")
    info = W.run_bundle(tmp_path / "man", tmp_path / "M", fake_render, status=False)
    assert (tmp_path / "man" / "result" / "chant.wav").exists() and info["duration"] == 0.3


def result_zip(tmp_path, with_json=True):
    sine(tmp_path / "rz" / "chant.wav")
    (tmp_path / "rz" / "result.json").write_text(json.dumps({"duration": 0.3, "pada_spans": [], "syllables": []}))
    if not with_json: (tmp_path / "rz" / "result.json").unlink()
    return B.zip_dir(tmp_path / "rz", tmp_path / "res.zip", prefix="result").read_bytes()


def test_manual_flow_via_api(client, monkeypatch, tmp_path):
    from backend.app import queue, db
    # earlier tests' app fixtures leak job-worker threads (all poll the same DB); serialize them so a job runs once
    real_run, lock = queue._run, threading.Lock()
    def once(j):
        with lock:
            if db.q1("SELECT status FROM jobs WHERE id=?", (j["id"],))["status"] == "queued": real_run(j)
    monkeypatch.setattr(queue, "_run", once)
    from backend.executors.manual import ManualExecutor
    monkeypatch.setattr(ManualExecutor, "poll_s", 0.05)
    monkeypatch.setattr(queue, "_align", lambda *a, **k: None)
    assert "colab_manual" in [e["name"] for e in client.get("/api/executors").json()]
    assert client.put("/api/settings", json={"executor": "nope"}).status_code == 422
    assert client.put("/api/settings", json={"colab_timeout_s": 99}).json()["colab_timeout_s"] == "99"
    client.post("/api/verses", json=GITA)
    mk = lambda ex: client.post("/api/jobs", json={"verse_id": "bg-2-47", "meter_id": "anushtubh", "executor": ex}).json()["id"]
    jid = mk("colab_manual")
    wait(client, jid, {"running"})
    for _ in range(50):
        r = client.get(f"/api/jobs/{jid}/bundle")
        if r.status_code == 200: break
        time.sleep(0.1)
    z = zipfile.ZipFile(io.BytesIO(r.content)); assert {"spec.json", "ref.wav"} <= set(z.namelist())
    assert client.put(f"/api/jobs/{jid}/result", content=b"junk").status_code == 422
    assert client.put(f"/api/jobs/{jid}/result", content=result_zip(tmp_path, False)).status_code == 422
    assert client.put(f"/api/jobs/{jid}/result", content=result_zip(tmp_path)).status_code == 200
    j = wait(client, jid, {"done", "failed"})
    assert j["status"] == "done", j
    assert client.put(f"/api/jobs/{jid}/result", content=b"x").status_code == 409      # no longer running
    assert client.get("/api/jobs/999/bundle").status_code == 404
    # non-manual job -> 409
    from backend.executors import local
    class Fake(local.Executor):
        name = "fake"
        def health(self): return {}
        def run(self, spec, workdir, on_progress, is_cancelled):
            while not is_cancelled(): time.sleep(0.05)
            raise Cancelled()
    monkeypatch.setitem(local.REGISTRY, "fake", Fake)
    j2 = mk("fake"); wait(client, j2, {"running"})
    assert client.put(f"/api/jobs/{j2}/result", content=b"x").status_code == 409
    assert client.get(f"/api/jobs/{j2}/bundle").status_code == 404
    client.post(f"/api/jobs/{j2}/cancel")
