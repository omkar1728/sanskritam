"""Single in-process worker thread; one job at a time (model needs ~3.4 GB)."""
import json, os, shutil, threading, time, traceback
from pathlib import Path
from . import config as C, db, verses, storage
from backend.executors.base import Cancelled
from backend.executors.local import get_executor
from backend.engine.mp3 import wav_to_mp3, LEAD_MS, TAIL_S

_cancel: set[int] = set()
_wake = threading.Event()
_started = False
_gen = 0          # bumped on each start(); older worker threads (tests restart the app) exit

def job_dir(jid: int) -> Path:
    return C.STORAGE / "jobs" / str(jid)

def submit(verse_id, meter_id, voice_id, executor, device, steps, seed) -> int:
    if not db.q1("SELECT 1 FROM verses WHERE id=?", (verse_id,)): raise KeyError("verse")
    if not db.q1("SELECT 1 FROM meters WHERE id=?", (meter_id,)): raise KeyError("meter")
    if not db.q1("SELECT 1 FROM voices WHERE id=? AND enabled", (voice_id,)): raise KeyError("voice")
    get_executor(executor)    # raises ValueError if unknown
    jid = db.q1("INSERT INTO jobs(verse_id,meter_id,voice_id,executor,device,steps,seed) VALUES(?,?,?,?,?,?,?) RETURNING id",
                (verse_id, meter_id, voice_id, executor, device, steps, seed))["id"]
    _wake.set()
    return jid

def cancel(jid: int) -> bool:
    j = db.q1("SELECT status FROM jobs WHERE id=?", (jid,))
    if not j: return False
    if j["status"] == "queued":
        db.x("UPDATE jobs SET status='cancelled', finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'", (jid,))
        return True
    if j["status"] in ("running", "aligning"):
        _cancel.add(jid); return True
    return False

def _log(jid, line, progress=None):
    if progress is not None and progress >= 0:
        db.x("UPDATE jobs SET progress=?, log=right(coalesce(log,'')||?, 20000) WHERE id=?", (min(progress, 0.99), line + "\n", jid))
    else:
        db.x("UPDATE jobs SET log=right(coalesce(log,'')||?, 20000) WHERE id=?", (line + "\n", jid))

def key(jid: int, name: str) -> str:
    return f"jobs/{jid}/{name}"

def _upload(jid, mp3, wav, apath) -> dict:
    st = storage.get()
    st.put_file(key(jid, "chant.mp3"), mp3, "audio/mpeg")
    st.put_file(key(jid, "chant.wav"), wav, "audio/wav")
    ak = None
    if apath:
        ak = key(jid, "alignment.json"); st.put_file(ak, apath, "application/json")
    return {"mp3": key(jid, "chant.mp3"), "wav": key(jid, "chant.wav"), "alignment": ak}

def _align(jid, wav, padas, wd):
    """Word/syllable alignment; on any failure the job still succeeds without alignment (line-level fallback)."""
    from backend.engine import align as A
    from backend.engine.synth import syllable_counts
    try:
        try:
            al = A.align(wav, padas, [p.split() for p in padas])
        except ValueError:                       # display-word mismatch: show SLP1 instead of Devanagari
            al = A.align(wav, padas)
        errs = A.validate(al, syllable_counts(padas))
        # A differing syllable COUNT only means the text-based counter and the aligner's syllabifier disagree
        # (e.g. on conjuncts); times stay valid, so keep the alignment and flag it. Timing errors still reject.
        soft = [e for e in errs if "syllables, expected" in e]
        errs = [e for e in errs if e not in soft]
        if errs:
            _log(jid, "alignment rejected: " + "; ".join(errs[:5])); return None
        if soft:
            al["syllable_count_note"] = "; ".join(soft)
            _log(jid, "alignment kept, syllable count differs from text count: " + "; ".join(soft))
        # the player plays the MP3, which has a lead-in and tail the WAV lacks
        A.shift(al, LEAD_MS / 1000, al["audio_duration"] + LEAD_MS / 1000 + TAIL_S)
        path = str(wd / "alignment.json")
        Path(path).write_text(json.dumps(al, ensure_ascii=False), encoding="utf-8")
        return path
    except Exception as e:
        _log(jid, f"alignment unavailable: {e}"); return None
    # The MMS_FA model stays loaded across chants (loading it was most of the per-chant time).
    # Callers free it with `release_aligner()`: before a render (RAM is 6 GB) and when the queue goes idle.

def release_aligner():
    from backend.engine import align as A
    A.unload()

def _run(j: dict):
    jid = j["id"]
    v = verses.present(db.q1("SELECT * FROM verses WHERE id=?", (j["verse_id"],)))
    m = db.q1("SELECT * FROM meters WHERE id=?", (j["meter_id"],))
    vo = db.q1("SELECT * FROM voices WHERE id=?", (j["voice_id"],))
    wd = job_dir(jid)
    spec = dict(padas=verses.padas(v["text"]), ref_wav=m["wav"], ref_text=m["ref_text"], sec_per_syll=m["sec_per_syll"],
                voice_ckpt=vo["checkpoint"], vocoder_ckpt=vo["vocoder"], out_wav=str(wd / "chant.wav"),
                steps=j["steps"], seed=j["seed"], device=j["device"])
    db.x("UPDATE jobs SET status='running', started_at=CURRENT_TIMESTAMP WHERE id=?", (jid,))
    try:
        release_aligner()                        # a render needs ~3.4 GB; do not hold MMS_FA (~1.2 GB) meanwhile
        res = get_executor(j["executor"]).run(spec, str(wd), lambda p, l: _log(jid, l, p), lambda: jid in _cancel)
        mp3 = str(wd / "chant.mp3")
        wav_to_mp3(res["wav"], mp3)
        db.x("UPDATE jobs SET status='aligning', progress=0.99 WHERE id=?", (jid,))
        apath = _align(jid, res["wav"], spec["padas"], wd)
        keys = _upload(jid, mp3, res["wav"], apath)
        db.x("INSERT INTO assets(job_id,mp3_key,wav_key,alignment_key,duration) VALUES(?,?,?,?,?) ON CONFLICT (job_id) DO UPDATE"
             " SET mp3_key=EXCLUDED.mp3_key, wav_key=EXCLUDED.wav_key, alignment_key=EXCLUDED.alignment_key, duration=EXCLUDED.duration",
             (jid, keys["mp3"], keys["wav"], keys["alignment"], res["duration"]))
        for p in (mp3, res["wav"], apath):      # job dir keeps only spec/logs once the files are in storage
            if p: Path(p).unlink(missing_ok=True)
        db.x("UPDATE jobs SET status='done', progress=1, finished_at=CURRENT_TIMESTAMP WHERE id=?", (jid,))
    except Cancelled:
        db.x("UPDATE jobs SET status='cancelled', finished_at=CURRENT_TIMESTAMP WHERE id=?", (jid,))
    except Exception as e:
        db.x("UPDATE jobs SET status='failed', error=?, finished_at=CURRENT_TIMESTAMP WHERE id=?", (str(e)[-4000:], jid))
    finally:
        _cancel.discard(jid)

def _loop(gen):
    while gen == _gen:
        try:
            j = db.q1("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1")
            if not j:
                release_aligner()
                _wake.wait(2); _wake.clear(); continue
            _run(j)
        except Exception:
            traceback.print_exc(); time.sleep(1)

def start():
    global _started, _gen
    if _started: return
    _gen += 1
    db.x("UPDATE jobs SET status='failed', error='server restarted' WHERE status IN ('running','aligning')")
    threading.Thread(target=_loop, args=(_gen,), daemon=True, name="job-worker").start()
    _started = True
