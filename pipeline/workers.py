"""Render and post worker processes (spawn context). Parent code only passes picklable data.

Messages
  in_q   (parent -> render): PlannedJob | None (sentinel)
  post_q (render/parent -> post): {"job": PlannedJob, "wav": path|None, "syllables": int, "duration": float,
                                   "render_s": float, "worker": str, "old": state-entry|None} | None (sentinel)
  result_q (workers -> parent): {"type": "result", "entry": dict, "mp3": bytes|None, "align": bytes|None,
                                 "wav": bytes|None, "metrics": dict}
"""
from __future__ import annotations

import os
import queue
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def make_entry(job, run_id: str, status: str, error: str | None = None, duration_s: float | None = None,
               syllables: int | None = None) -> dict:
    rec, p = job.record, job.params
    return {
        "verse_id": rec.verse_id, "work": rec.work, "book": rec.book, "chapter": rec.chapter, "seq": rec.seq,
        "status": status, "error": error, "text_variant": rec.text_variant, "text_fallback": rec.text_fallback,
        "duration_s": duration_s, "syllables": syllables, "text_sha256": rec.text_sha256(),
        "params_hash": job.params_hash, "steps": p.get("steps"), "seed": p.get("seed"), "voice": p.get("voice"),
        "meter": p.get("meter"), "mp3_kbps": p.get("mp3_kbps"), "run_id": run_id, "created_at": now_iso(),
        "extra": rec.extra,
    }


def failed_result(job, run_id: str, error: str, worker: str, kind: str, **metrics) -> dict:
    return {"type": "result", "entry": make_entry(job, run_id, "failed", error[-1000:]), "mp3": None, "align": None,
            "wav": None, "metrics": {"worker": worker, "kind": kind, **metrics}}


def _short_err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:800]


# --------------------------------------------------------------------------- render worker
def render_worker(worker_id: str, gpu_index: int | None, device: str, in_q, post_q, result_q, scratch: str,
                  run_id: str) -> None:
    """Loads the engine once (lazily on the first job), renders verses to scratch WAVs."""
    if device == "cuda" and gpu_index is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_index)      # before torch is imported in this fresh process
    from . import engine_io as E
    eng = None
    wav_dir = Path(scratch) / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    while True:
        job = in_q.get()
        if job is None:
            break
        rec = job.record
        t0 = time.time()
        try:
            if eng is None:
                eng = E.make_engine()
            wav = wav_dir / f"{rec.verse_id}.{run_id}.wav"
            spec = E.build_render_spec(job.params, rec, str(wav), device)
            res = eng.render(spec)
            for m in res.get("mels") or []:
                Path(m).unlink(missing_ok=True)
            post_q.put({"job": job, "wav": res["wav"], "syllables": int(sum(res.get("syllables") or [])),
                        "duration": float(res["duration"]), "render_s": time.time() - t0, "worker": worker_id,
                        "old": None})
        except BaseException as e:                                  # per-verse failure never kills the worker
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            traceback.print_exc()
            result_q.put(failed_result(job, run_id, "render_error: " + _short_err(e), worker_id, "render",
                                       render_s=time.time() - t0))
    if eng is not None:
        try:
            eng.unload()
        except Exception:
            pass


# --------------------------------------------------------------------------- post worker
def post_worker(worker_id: str, post_q, result_q, scratch: str, run_id: str, cfg: dict, store_uri: str | None) -> None:
    """WAV -> align (with retries) -> MP3 -> result. reuse='wav' jobs read WAV + MP3 from the old segment."""
    from . import engine_io as E
    store = None
    tmp = Path(scratch) / "post"
    tmp.mkdir(parents=True, exist_ok=True)
    retries = int(cfg.get("align_retries", 2))
    keep_wav = bool(cfg.get("keep_wav"))
    device = cfg.get("align_device", "cpu")
    while True:
        msg = post_q.get()
        if msg is None:
            break
        job = msg["job"]
        rec = job.record
        t0 = time.time()
        wav_path = msg.get("wav")
        temp_files: list[Path] = []
        try:
            m: dict = {"worker": worker_id, "kind": "post", "render_s": msg.get("render_s", 0.0), "reuse": bool(msg.get("old"))}
            if job.reuse == "wav":
                if store is None:
                    from .stores import open_store
                    store = open_store(store_uri)
                old = msg["old"]
                wav_bytes_old = E.read_old_blob(store, old, "wav")
                wav_path = str(tmp / f"{rec.verse_id}.{run_id}.reuse.wav")
                Path(wav_path).write_bytes(wav_bytes_old)
                temp_files.append(Path(wav_path))
                mp3_bytes = E.read_old_blob(store, old, "audio")
                duration = old.get("duration_s")
                syllables = old.get("syllables")
            else:
                mp3_bytes = None
                duration = (msg.get("duration") or E.wav_duration(wav_path)) + E.LEAD_MS / 1000 + E.TAIL_S
                syllables = msg.get("syllables")

            ta = time.time()
            al, err = E.align_with_retries(wav_path, rec.padas, retries, device=device)
            m["align_s"] = time.time() - ta
            m["align_attempts"] = E.align_with_retries.last_attempts

            if mp3_bytes is None:
                tm = time.time()
                mp3_path = tmp / f"{rec.verse_id}.{run_id}.mp3"
                temp_files.append(mp3_path)
                E.encode_mp3(wav_path, str(mp3_path), int(job.params.get("mp3_kbps", 192)))
                mp3_bytes = mp3_path.read_bytes()
                m["mp3_s"] = time.time() - tm

            wav_blob = None
            if al is None:
                wav_blob = Path(wav_path).read_bytes()              # D14: kept for a later re-align
                entry = make_entry(job, run_id, "align_failed", err, duration, syllables)
                align_bytes = None
            else:
                entry = make_entry(job, run_id, "ok", None, duration, syllables)
                align_bytes = E.align_json_bytes(al)
            m["post_s"] = time.time() - t0
            result_q.put({"type": "result", "entry": entry, "mp3": mp3_bytes, "align": align_bytes,
                          "wav": wav_blob, "metrics": m})
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            traceback.print_exc()
            result_q.put(failed_result(job, run_id, "post_error: " + _short_err(e), worker_id, "post",
                                       post_s=time.time() - t0))
        finally:
            for f in temp_files:
                f.unlink(missing_ok=True)
            if wav_path and job.reuse != "wav" and not keep_wav:
                Path(wav_path).unlink(missing_ok=True)


def drain(q) -> int:
    """Empty an mp.Queue without blocking; returns how many items were dropped."""
    n = 0
    while True:
        try:
            q.get(timeout=0.2)
            n += 1
        except queue.Empty:
            return n
        except Exception:
            return n
