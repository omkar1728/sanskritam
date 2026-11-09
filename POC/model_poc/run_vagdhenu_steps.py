"""Vagdhenu step-count benchmark: render the SAME verse (Bala sarga 1, verse 1) at several DiT step counts.

Per run it records wall time, peak VRAM (torch allocated/reserved + nvidia-smi used), RSS (sampled peak + ru_maxrss),
GPU util and process/system CPU util (sampled every --interval s while the render runs). One model load, one discarded
warm-up render, then --repeats passes over all steps (steps interleaved per pass, so clock/thermal drift is spread out).
Same text, seed, reference clip and voice for every run; only `steps` changes.
    PYTHONPATH=. python POC/model_poc/run_vagdhenu_steps.py [--steps 16 18 ...] [--repeats 3]
Output: $POC_OUT/vagdhenu_steps/{step_SS_rR.wav, results.json, steps.csv}. Sound quality is a USER-CHECK.
"""
import argparse, csv, json, os, subprocess, sys, threading, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import common as K
import psutil, torch
from backend.app import config as C
from backend.engine.synth import Engine, RenderSpec

STEPS = [16, 32, 48, 64, 18, 20, 22, 24, 26, 28, 30]      # as requested; run in sorted order
ap = argparse.ArgumentParser()
ap.add_argument("--steps", type=int, nargs="+", default=STEPS)
ap.add_argument("--repeats", type=int, default=3)
ap.add_argument("--interval", type=float, default=0.5, help="sampling period in seconds")
ap.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
ap.add_argument("--voice", default="voice_armA_ema_2026-06-11.pt")
ap.add_argument("--vocoder", default="voc_bigvgan_EMA_2026-06-11.pth")
a = ap.parse_args()
steps = sorted(set(a.steps))
dev = K.device()
assert dev == "cuda", "this benchmark is meant for the T4; set POC_DEVICE=cuda and check torch.cuda.is_available()"

out = K.OUT / "vagdhenu_steps"; out.mkdir(parents=True, exist_ok=True)
verse = K.load_verses(1)[0]
ref = K.reference_clip()
proc = psutil.Process()
ncpu = psutil.cpu_count()


def smi():
    """(gpu util %, gpu mem used MiB) from nvidia-smi, or (None, None)."""
    try:
        o = subprocess.check_output(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                                    text=True, timeout=2).split("\n")[0].split(",")
        return float(o[0]), float(o[1])
    except Exception:
        return None, None


class Sampler(threading.Thread):
    def __init__(self, interval):
        super().__init__(daemon=True); self.interval = interval; self.stop = threading.Event(); self.rows = []

    def run(self):
        proc.cpu_percent(None); psutil.cpu_percent(None)
        while not self.stop.wait(self.interval):
            g, m = smi()
            self.rows.append({"gpu_util": g, "gpu_mem_mib": m, "rss_gb": proc.memory_info().rss / 1024 ** 3,
                              "proc_cpu": proc.cpu_percent(None),            # % of ONE core (can exceed 100 with threads)
                              "sys_cpu": psutil.cpu_percent(None)})          # % of all cores

    def summary(self):
        def col(k): return [r[k] for r in self.rows if r[k] is not None]
        def mean(x): return round(sum(x) / len(x), 1) if x else None
        def mx(x): return round(max(x), 1) if x else None
        return {"samples": len(self.rows), "gpu_util_mean": mean(col("gpu_util")), "gpu_util_max": mx(col("gpu_util")),
                "gpu_mem_smi_peak_mib": mx(col("gpu_mem_mib")), "rss_peak_gb": round(max(col("rss_gb"), default=0), 2),
                "proc_cpu_mean": mean(col("proc_cpu")), "proc_cpu_max": mx(col("proc_cpu")),
                "sys_cpu_mean": mean(col("sys_cpu")), "sys_cpu_max": mx(col("sys_cpu"))}


def render(eng, st, wav):
    spec = RenderSpec(padas=verse["padas"], ref_wav=ref["wav"], ref_text=ref["ref_text"], sec_per_syll=ref["sec_per_syll"],
                      voice_ckpt=str(C.MODELS / a.voice), vocoder_ckpt=str(C.MODELS / a.vocoder), out_wav=str(wav),
                      steps=st, seed=a.seed, device=dev)
    return eng.render(spec)


meta = {"verse": verse["id"], "padas": verse["padas"], "seed": a.seed, "voice": a.voice, "vocoder": a.vocoder,
        "repeats": a.repeats, "steps": steps, "interval_s": a.interval, "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__, "vcpus": ncpu, "ram_total_gb": round(psutil.virtual_memory().total / 1024 ** 3, 1)}
K.log(meta)
eng = Engine()
t = time.time()
render(eng, min(steps), out / "warmup.wav")                  # loads models, warms CUDA kernels; not measured
meta["warmup_incl_load_s"] = round(time.time() - t, 2)
K.log("warm-up done", meta["warmup_incl_load_s"], "s")

runs = []
for r in range(1, a.repeats + 1):
    for st in steps:
        wav = out / f"step_{st:02d}_r{r}.wav"
        torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
        s = Sampler(a.interval); s.start()
        t = time.time(); res = render(eng, st, wav); torch.cuda.synchronize(); wall = time.time() - t
        s.stop.set(); s.join()
        row = {"steps": st, "repeat": r, "wall_s": round(wall, 2), "audio_s": round(res["duration"], 2),
               "rtf": round(wall / res["duration"], 3), "syllables": res["syllables"],
               "vram_alloc_peak_gb": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2),
               "vram_reserved_peak_gb": round(torch.cuda.max_memory_reserved() / 1024 ** 3, 2),
               "ru_maxrss_gb": round(K.peak_rss_gb(), 2), **s.summary()}
        runs.append(row); K.log(row)
        (out / "results.json").write_text(json.dumps({"meta": meta, "runs": runs}, indent=1, ensure_ascii=False), encoding="utf-8")
        for p in out.glob(f"{wav.name}.mel*.npy"): p.unlink()          # engine side files, not needed

with open(out / "steps.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(runs[0])); w.writeheader(); w.writerows(runs)
(out / "warmup.wav").unlink(missing_ok=True)
K.log("wrote", out / "results.json", out / "steps.csv")
