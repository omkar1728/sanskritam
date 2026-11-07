"""Epic batch API tests. All verse text below is FIXTURE placeholder data, not real verses."""
import io, json, shutil, time, zipfile
from pathlib import Path
import pytest
from test_api import client, wait  # noqa: F401
from backend.app import db

WAV = Path(__file__).resolve().parents[2] / "POC" / "outputs" / "gita_2_47_default.wav"
L1, L2 = "कर्मण्येवाधिकारस्ते मा फलेषु कदाचन", "मा कर्मफलहेतुर्भूर्मा ते सङ्गोऽस्त्वकर्मणि"   # FIXTURE

def put_verse(vid, kanda, sarga, seq, *, pd=None, cl=None, vl=None, refs=None):
    text = {}
    if pd or cl: text["critical_smith"] = {"punctuated_derived": pd, "lines": cl}
    if vl: text["vulgate_net"] = {"lines": vl}
    data = {"id": vid, "FIXTURE": True, "refs": refs or {}, "text": text}
    db.x("INSERT INTO epic_verses(id,epic,kanda,sarga,seq,kind,data) VALUES(?,?,?,?,?,?,?::jsonb)",
         (vid, "ramayana", kanda, sarga, seq, "critical", json.dumps(data, ensure_ascii=False)))

@pytest.fixture()
def fx(client):
    put_verse("baala-001-001", 1, 1, 1, pd=f"{L1} ।\n{L2} ॥", cl=[L1, L2], refs={"critical_smith": {"sarga": 1, "verse": 7}})
    put_verse("baala-001-002", 1, 1, 2, cl=[L1, L2])
    put_verse("baala-002-001", 1, 2, 1, vl=[L1, L2])
    put_verse("baala-002-002", 1, 2, 2)                      # no text at all
    put_verse("ayodhya-001-001", 2, 1, 1, cl=[L1, L2])
    return client

BODY = {"epic": "ramayana", "kanda": 1, "voice_id": "steer", "steps": 8, "seed": 1}

def test_preview_and_materialise(fx):
    r = fx.post("/api/epic-batches/preview", json=BODY).json()
    assert (r["total"], r["to_generate"], r["skipped"], r["unavailable"]) == (4, 3, 0, 1)
    assert r["meters"][0]["count"] == 3 and len(r["sample"]) == 3
    assert r["sample"][0] == {"id": "ramayana-baala-001-001", "ref": "1.1.7", "meter_id": r["sample"][0]["meter_id"]}
    assert db.q1("SELECT count(*) c FROM verses")["c"] == 0          # preview materialises nothing
    whole = fx.post("/api/epic-batches/preview", json=dict(BODY, kanda=None)).json()
    assert whole["to_generate"] == 4
    one = fx.post("/api/epic-batches/preview", json=dict(BODY, kanda=None, verse_id="baala-002-001")).json()
    assert one["to_generate"] == 1
    ov = fx.post("/api/epic-batches/preview", json=dict(BODY, meter_id="anushtubh")).json()
    assert ov["meters"] == [{"meter_id": "anushtubh", "count": 3}]
    assert fx.post("/api/epic-batches/preview", json=dict(BODY, voice_id="nope")).status_code == 422

def test_confirm_and_create(fx):
    assert fx.post("/api/epic-batches", json=BODY).status_code == 422
    assert fx.post("/api/epic-batches", json=dict(BODY, confirm=True, kanda=None)).status_code == 422   # needs confirm_all
    assert fx.post("/api/epic-batches", json=dict(BODY, confirm=True, kanda=1, sarga=99)).status_code == 422  # nothing
    r = fx.post("/api/epic-batches", json=dict(BODY, confirm=True))
    assert r.status_code == 201
    r = r.json(); assert r["count"] == 3 and len(r["job_ids"]) == 3
    v = fx.get("/api/verses/ramayana-baala-001-001").json()
    assert v["text"] == [L1 + " ।", L2 + " ॥"] and v["source"]["reference"] == "1.1.7"
    assert v["source"]["work"] == "Valmiki Ramayana" and "Critical" in v["source"]["edition"]
    v3 = fx.get("/api/verses/ramayana-baala-002-001").json()
    assert v3["text"] == [L1, L2] and v3["source"]["reference"] == "1.2.1" and "vulgate" in v3["source"]["edition"]
    js = db.q("SELECT * FROM jobs WHERE batch_id=?", (r["batch_id"],))
    assert {j["executor"] for j in js} == {"colab_batch"} and {j["status"] for j in js} == {"awaiting_result"}
    b = fx.get(f"/api/epic-batches/{r['batch_id']}").json()
    assert len(b["jobs"]) == 3 and b["counts"] == {"awaiting_result": 3}
    assert fx.get("/api/epic-batches").json()[0]["counts"] == {"awaiting_result": 3}
    assert fx.get("/api/epic-batches/9999").status_code == 404
    # idempotent materialisation: second batch for another kanda reuses nothing, verses unchanged
    fx.post("/api/epic-batches", json=dict(BODY, confirm=True, confirm_all=True, kanda=None))
    assert db.q1("SELECT count(*) c FROM verses")["c"] == 4

def test_skip_done_and_cap(fx, monkeypatch):
    bid = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()
    j = db.q1("SELECT id,meter_id FROM jobs WHERE batch_id=? ORDER BY id LIMIT 1", (bid["batch_id"],))
    db.x("UPDATE jobs SET status='done' WHERE id=?", (j["id"],))
    r = fx.post("/api/epic-batches/preview", json=BODY).json()
    assert (r["skipped"], r["to_generate"]) == (1, 2)
    assert fx.post("/api/epic-batches/preview", json=dict(BODY, steps=9)).json()["skipped"] == 0
    from backend.app import epic_jobs
    monkeypatch.setattr(epic_jobs, "MAX_BATCH_JOBS", 1)
    r = fx.post("/api/epic-batches", json=dict(BODY, confirm=True))
    assert r.status_code == 422 and "cap" in r.json()["detail"]

def test_input_zip(fx):
    bid = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()["batch_id"]
    r = fx.get(f"/api/epic-batches/{bid}/input.zip")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content)); names = z.namelist()
    bj = json.loads(z.read("batch.json"))
    assert len(bj["jobs"]) == 3
    s = bj["jobs"][0]["spec"]
    assert s["ref_wav"].startswith("refs/") and s["ref_wav"] in names
    assert s["voice_ckpt"].startswith("models/") and "/" not in s["voice_ckpt"][7:] and s["steps"] == 8
    assert len([n for n in names if n.startswith("refs/")]) == 1          # one ref wav per meter
    assert fx.get("/api/epic-batches/777/input.zip").status_code == 404
    first = bj["jobs"][0]["job_id"]
    db.x("UPDATE jobs SET status='failed' WHERE id=?", (first,))
    z = zipfile.ZipFile(io.BytesIO(fx.get(f"/api/epic-batches/{bid}/input.zip").content))
    assert first not in [j["job_id"] for j in json.loads(z.read("batch.json"))["jobs"]]

def test_input_zip_code(fx):
    import ast, re
    from backend.app import batch_io
    bid = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()["batch_id"]
    z = zipfile.ZipFile(io.BytesIO(fx.get(f"/api/epic-batches/{bid}/input.zip").content)); names = set(z.namelist())
    assert "code/backend/worker/colab_worker.py" in names and "code/backend/engine/synth.py" in names
    assert not [n for n in names if re.search(r"tests/|__pycache__|\.pyc$|\.env|\.db$|\.sqlite$", n)]
    # import closure of the worker, executors.bundle and engine.synth stays inside the zip
    todo = ["backend.worker.colab_worker", "backend.engine.synth", "backend.executors.bundle"]; seen = set()
    while todo:
        m = todo.pop()
        if m in seen: continue
        seen.add(m)
        base = "code/" + m.replace(".", "/")
        f = base + ".py" if base + ".py" in names else base + "/__init__.py"
        assert f in names, m
        pkg = m if f.endswith("__init__.py") else m.rpartition(".")[0]
        for node in ast.walk(ast.parse(z.read(f).decode())):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level: mod = ".".join(pkg.split(".")[: len(pkg.split(".")) - node.level + 1] + ([mod] if mod else []))
                if mod.startswith("backend"):
                    todo.append(mod)
                    todo += [mod + "." + a.name for a in node.names if "code/" + (mod + "." + a.name).replace(".", "/") + ".py" in names]
            elif isinstance(node, ast.Import):
                todo += [a.name for a in node.names if a.name.startswith("backend")]
    for pk in ("backend", "backend.app", "backend.engine", "backend.executors", "backend.worker"):
        assert "code/" + pk.replace(".", "/") + "/__init__.py" in names, pk
    v = json.loads(z.read("batch.json"))["code_version"]
    assert v == batch_io.code_version() == batch_io.code_version() and len(v) == 12

def _results(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items(): z.writestr(k, v)
    return b.getvalue()

def test_result_upload_and_pipeline(fx, monkeypatch):
    from backend.app import queue
    monkeypatch.setattr(queue, "_align", lambda *a, **k: None)
    monkeypatch.setattr(queue, "wav_to_mp3", lambda w, m: Path(m).write_bytes(b"mp3"))
    bid = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()
    ids = bid["job_ids"]; bid = bid["batch_id"]
    time.sleep(0.5)
    assert {db.q1("SELECT status FROM jobs WHERE id=?", (i,))["status"] for i in ids} == {"awaiting_result"}   # loop ignores them
    other = fx.post("/api/epic-batches", json=dict(BODY, kanda=2, confirm=True)).json()["job_ids"][0]
    wav = WAV.read_bytes(); info = json.dumps({"duration": 1.5, "pada_spans": [[0, 1]], "syllables": [16]})
    z = _results({f"{ids[0]}/chant.wav": wav, f"{ids[0]}/result.json": info,
                  f"{other}/chant.wav": wav, f"{other}/result.json": info,       # foreign batch
                  f"{ids[2]}/chant.wav": wav,                                     # incomplete
                  "abc/chant.wav": b"x", "007/chant.wav": b"x",
                  "errors.json": json.dumps({str(ids[1]): "RuntimeError: boom", str(other): "x", "../1": "y"})})
    r = fx.put(f"/api/epic-batches/{bid}/result", content=z)
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 1, "failed": 1, "ignored": 3}
    assert fx.put(f"/api/epic-batches/{bid}/result", content=_results({"../evil/chant.wav": b"x"})).status_code == 422
    assert db.q1("SELECT status FROM jobs WHERE id=?", (other,))["status"] == "awaiting_result"
    assert db.q1("SELECT status,error FROM jobs WHERE id=?", (ids[1],)) == {"status": "failed", "error": "RuntimeError: boom"}
    assert db.q1("SELECT status FROM jobs WHERE id=?", (ids[2],))["status"] == "awaiting_result"
    j = wait(fx, ids[0], {"done", "failed"})
    assert j["status"] == "done" and j["executor"] == "colab_staged" and j["asset"]["duration"] == 1.5
    assert fx.get(f"/api/jobs/{ids[0]}/audio.mp3").content == b"mp3"
    assert fx.put(f"/api/epic-batches/{bid}/result", content=b"notzip").status_code == 422
    assert fx.put("/api/epic-batches/555/result", content=z).status_code == 404

def test_hidden_executors(fx):
    names = [e["name"] for e in fx.get("/api/executors").json()]
    assert "colab_batch" not in names and "colab_staged" not in names and "local" in names
    assert fx.put("/api/settings", json={"executor": "colab_batch"}).status_code == 422
    from backend.executors.local import get_executor
    with pytest.raises(RuntimeError): get_executor("colab_batch").run({}, "x", None, None)

def test_result_zip_with_results_prefix(fx, monkeypatch):
    """Layout written by notebooks/colab_batch.ipynb: everything under results/."""
    from backend.app import queue
    monkeypatch.setattr(queue, "_align", lambda *a, **k: None)
    monkeypatch.setattr(queue, "wav_to_mp3", lambda w, m: Path(m).write_bytes(b"mp3"))
    r0 = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()
    ids, bid = r0["job_ids"], r0["batch_id"]
    wav = WAV.read_bytes(); info = json.dumps({"duration": 1.5, "pada_spans": [[0, 1]], "syllables": [16]})
    z = _results({f"results/{ids[0]}/chant.wav": wav, f"results/{ids[0]}/result.json": info,
                  "results/errors.json": json.dumps({str(ids[1]): "RuntimeError: boom"})})
    r = fx.put(f"/api/epic-batches/{bid}/result", content=z)
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 1, "failed": 1, "ignored": 0}
    assert wait(fx, ids[0], {"done", "failed"})["status"] == "done"


# ---- result paths + Drive folder import (FIXTURE data) ----
def test_result_dir_for():
    from backend.app import batch_io
    assert batch_io.result_dir_for("ramayana-baala-001-001") == "batch_results/ramayana/baala/sarga_001/baala-001-001"
    assert batch_io.result_dir_for("ayodhya-012-103") == "batch_results/ramayana/ayodhya/sarga_012/ayodhya-012-103"
    for bad in ("../x", "baala-1", "", "ramayana-baala-001-001/../x"):
        with pytest.raises(batch_io.BatchIOError): batch_io.result_dir_for(bad)

def test_input_zip_result_dirs(fx):
    bid = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()["batch_id"]
    bj = json.loads(zipfile.ZipFile(io.BytesIO(fx.get(f"/api/epic-batches/{bid}/input.zip").content)).read("batch.json"))
    assert bj["results_root"] == "batch_results" and bj["batch_dir"] == f"batch_results/_batches/{bid}"
    dirs = {j["verse_id"]: j["result_dir"] for j in bj["jobs"]}
    assert dirs["ramayana-baala-001-001"] == "batch_results/ramayana/baala/sarga_001/baala-001-001"
    assert all(".." not in d and not d.startswith("/") for d in dirs.values())

def _drive(fx, tmp_path, monkeypatch):
    from backend.app import queue
    monkeypatch.setattr(queue, "_align", lambda *a, **k: None)
    monkeypatch.setattr(queue, "wav_to_mp3", lambda w, m: Path(m).write_bytes(b"mp3"))
    r0 = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()
    base = tmp_path / "drive"; base.mkdir()
    assert fx.put("/api/settings", json={"colab_drive_dir": str(base)}).status_code == 200
    return r0["job_ids"], r0["batch_id"], base

def _put(base, job, dur=1.5):
    from backend.app import batch_io
    d = base / batch_io.result_dir_for(db.q1("SELECT verse_id FROM jobs WHERE id=?", (job,))["verse_id"]); d.mkdir(parents=True)
    shutil.copyfile(WAV, d / "chant.wav")
    (d / "result.json").write_text(json.dumps({"duration": dur, "pada_spans": [[0, 1]], "syllables": [16]}))

def test_import_drive_happy_partial_errors(fx, tmp_path, monkeypatch):
    ids, bid, base = _drive(fx, tmp_path, monkeypatch)
    assert fx.post("/api/epic-batches/999/import-drive").status_code == 404
    r = fx.post(f"/api/epic-batches/{bid}/import-drive")
    assert r.json() == {"accepted": 0, "failed": 0, "ignored": 0, "missing": 3}
    _put(base, ids[0])
    (base / "batch_results/_batches" / str(bid)).mkdir(parents=True)
    (base / "batch_results/_batches" / str(bid) / "errors.json").write_text(json.dumps({str(ids[1]): "RuntimeError: boom"}))
    r = fx.post(f"/api/epic-batches/{bid}/import-drive")
    assert r.status_code == 200 and r.json() == {"accepted": 1, "failed": 1, "ignored": 0, "missing": 1}
    assert db.q1("SELECT status,error FROM jobs WHERE id=?", (ids[1],)) == {"status": "failed", "error": "RuntimeError: boom"}
    assert wait(fx, ids[0], {"done", "failed"})["status"] == "done"
    assert fx.post(f"/api/epic-batches/{bid}/import-drive").json() == {"accepted": 0, "failed": 0, "ignored": 0, "missing": 1}  # idempotent
    assert db.q1("SELECT status FROM jobs WHERE id=?", (ids[2],))["status"] == "awaiting_result"

def test_import_drive_bad_setting_symlink_and_invalid(fx, tmp_path, monkeypatch):
    ids, bid, base = _drive(fx, tmp_path, monkeypatch)
    assert fx.put("/api/settings", json={"colab_drive_dir": ""}).status_code == 200
    assert fx.post(f"/api/epic-batches/{bid}/import-drive").status_code == 400
    fx.put("/api/settings", json={"colab_drive_dir": str(tmp_path / "nope")})
    assert fx.post(f"/api/epic-batches/{bid}/import-drive").status_code == 400
    fx.put("/api/settings", json={"colab_drive_dir": str(base)})
    # symlinked result folder pointing outside base is ignored
    outside = tmp_path / "outside"; _put(outside, ids[0])
    from backend.app import batch_io
    link = base / batch_io.result_dir_for("ramayana-baala-001-001"); link.parent.mkdir(parents=True)
    link.symlink_to(outside / batch_io.result_dir_for("ramayana-baala-001-001"), target_is_directory=True)
    # bad duration for the second job
    _put(base, ids[1], dur=0)
    r = fx.post(f"/api/epic-batches/{bid}/import-drive").json()
    assert r == {"accepted": 0, "failed": 0, "ignored": 1, "missing": 2}
    assert db.q1("SELECT count(*) c FROM jobs WHERE batch_id=? AND status='awaiting_result'", (bid,))["c"] == 3

def test_alignment_upload_detects_batch(fx, monkeypatch):
    """Drop-in upload: no batch id given; batches are found from the job ids in the zip."""
    from backend.app import queue
    monkeypatch.setattr(queue, "_align", lambda *a, **k: None)
    monkeypatch.setattr(queue, "wav_to_mp3", lambda w, m: Path(m).write_bytes(b"mp3"))
    r0 = fx.post("/api/epic-batches", json=dict(BODY, confirm=True)).json()
    ids = r0["job_ids"]
    wav = WAV.read_bytes(); info = json.dumps({"duration": 1.5, "pada_spans": [[0, 1]], "syllables": [16]})
    z = _results({f"results/{ids[0]}/chant.wav": wav, f"results/{ids[0]}/result.json": info,
                  f"results/{ids[2]}/chant.wav": wav, f"results/{ids[2]}/result.json": info,
                  "results/errors.json": json.dumps({str(ids[1]): "RuntimeError: boom"})})
    r = fx.put("/api/alignment/upload", content=z)
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 2, "failed": 1, "ignored": 0, "batches": [r0["batch_id"]], "job_ids": sorted(ids)}
    assert wait(fx, ids[0], {"done", "failed"})["status"] == "done"
    assert fx.put("/api/alignment/upload", content=z).status_code == 422          # nothing waiting any more
    assert fx.put("/api/alignment/upload", content=b"notzip").status_code == 422
    assert fx.put("/api/alignment/upload", content=_results({"../evil/chant.wav": b"x"})).status_code == 422
