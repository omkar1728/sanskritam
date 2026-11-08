"""Alignment benchmark: run backend.engine.align (MMS_FA) on every wav the model POCs produced.

Run AFTER the model scripts (separate process: one model at a time). Records, per model and verse:
model load time (first call), align wall time, RTF, peak RAM/GPU, validate() problems, syllable count.
Writes outputs/<model>/align_<device>.json and alignment json per verse (outputs/<model>/<verse>.align.json).
    PYTHONPATH=. python POC/model_poc/run_align.py [--devices cpu cuda]
Alignment accuracy vs. audible words is a USER-CHECK (Claude cannot hear audio).
"""
import argparse, json, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import common as K
from backend.engine import align as A

ap = argparse.ArgumentParser()
ap.add_argument("--devices", nargs="+", default=["cpu", "cuda"], help="cuda is skipped if unavailable; the app uses cpu")
a = ap.parse_args()

import torch
verses = {v["id"]: v for v in json.loads((K.OUT / "verses_used.json").read_text(encoding="utf-8"))}
models = sorted(p.parent.name for p in K.OUT.glob("*/results.json"))
for dev in a.devices:
    if dev == "cuda" and not torch.cuda.is_available():
        K.log("cuda unavailable, skipping"); continue
    for m in models:
        out = {"model": m, "device": dev, "verses": {}}
        A.unload()
        if dev == "cuda": torch.cuda.reset_peak_memory_stats()
        t = time.time(); A._get_model(dev); out["load_s"] = round(time.time() - t, 2)
        for vid, v in verses.items():
            wav = K.OUT / m / f"{vid}.wav"
            if not wav.exists(): continue
            t = time.time()
            try:
                al = A.align(str(wav), v["padas"], device=dev)
                wall = time.time() - t
                errs = A.validate(al)
                (K.OUT / m / f"{vid}.align.json").write_text(json.dumps(al, ensure_ascii=False), encoding="utf-8")
                n_syl = sum(len(w["syllables"]) for ln in al["lines"] for w in ln["words"])
                r = {"ok": not errs, "problems": errs, "audio_s": al["audio_duration"], "syllables": n_syl}
            except Exception as e:
                wall = time.time() - t
                r = {"ok": False, "problems": [f"{type(e).__name__}: {e}"], "audio_s": None, "syllables": None}
            r.update(wall_s=round(wall, 2), rtf=round(wall / r["audio_s"], 3) if r["audio_s"] else None,
                     peak_rss_gb=round(K.peak_rss_gb(), 2), peak_gpu_gb=K.gpu_peak_gb())
            out["verses"][vid] = r
            K.log(dev, m, vid, r)
        (K.OUT / m / f"align_{dev}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
